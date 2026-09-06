from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.auth.deps import get_current_user
from backend.auth.teacher import get_teacher
from backend.db import get_session
from backend.models.auth_models import Attempt, ErrorEvent, Folder, Problem, User
from backend.models.classroom_models import (
    Assignment,
    AssignmentItem,
    ClassMembership,
    Classroom,
    StudentAssignmentItem,
)
from backend.routes.problem import _ensure_default_folder, _problem_response
from backend.schemas.classroom import (
    AssignmentDetail,
    AssignmentItemResponse,
    AssignmentPolicyUpdate,
    AssignmentSummary,
    ClassCreateRequest,
    ClassResponse,
    ClassroomAttemptResponse,
    CommonError,
    JoinClassRequest,
    StartItemResponse,
    StudentAssignmentItemResponse,
    StudentAssignmentResponse,
    StudentIdentity,
    StudentProgress,
    StudentWorkItem,
    StudentWorkResponse,
)
from backend.storage.r2 import (
    R2ConfigurationError,
    delete_bytes,
    presigned_get_url,
    upload_bytes,
)

router = APIRouter(tags=["classrooms"])
logger = logging.getLogger(__name__)
MAX_IMAGES = 12
MAX_FILE_BYTES = 7 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
COMPLETED_VERDICTS = {"fully_solved", "fully_correct"}
ATTENTION_VERDICTS = {"incorrect", "unclear"}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _members(session: Session, class_id: UUID) -> list[User]:
    return list(
        session.exec(
            select(User)
            .join(ClassMembership, ClassMembership.user_id == User.id)
            .where(ClassMembership.class_id == class_id, User.is_active == True)
            .order_by(User.full_name, User.id)
        ).all()
    )


def _class_response(session: Session, classroom: Classroom) -> ClassResponse:
    return ClassResponse(
        id=classroom.id,
        name=classroom.name,
        join_code=classroom.join_code,
        student_count=len(_members(session, classroom.id)),
    )


def _owned_class(session: Session, class_id: UUID, teacher: User) -> Classroom:
    classroom = session.exec(
        select(Classroom).where(
            Classroom.id == class_id, Classroom.teacher_id == teacher.id
        )
    ).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    return classroom


def _owned_assignment(
    session: Session, assignment_id: UUID, teacher: User
) -> tuple[Assignment, Classroom]:
    row = session.exec(
        select(Assignment, Classroom)
        .join(Classroom, Assignment.class_id == Classroom.id)
        .where(Assignment.id == assignment_id, Classroom.teacher_id == teacher.id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return row


def _items(session: Session, assignment_id: UUID) -> list[AssignmentItem]:
    return list(
        session.exec(
            select(AssignmentItem)
            .where(AssignmentItem.assignment_id == assignment_id)
            .order_by(AssignmentItem.position)
        ).all()
    )


def _summary(
    session: Session,
    assignment: Assignment,
    classroom: Classroom,
    items: list[AssignmentItem] | None = None,
) -> AssignmentSummary:
    return AssignmentSummary(
        id=assignment.id,
        class_id=classroom.id,
        class_name=classroom.name,
        title=assignment.title,
        allow_reveal=assignment.allow_reveal,
        item_count=len(items if items is not None else _items(session, assignment.id)),
        created_at=_utc(assignment.created_at),
    )


def _asset_url(key: str | None) -> str | None:
    if not key:
        return None
    try:
        return presigned_get_url(key=key, expires_in_seconds=900)
    except R2ConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail=f"Artifact storage is not configured: {exc}"
        ) from exc


def _item_response(item: AssignmentItem) -> AssignmentItemResponse:
    return AssignmentItemResponse(
        id=item.id,
        title=item.title,
        position=item.position,
        image_url=_asset_url(item.image_key),
    )


def _linked_problems(
    session: Session, assignment_id: UUID, user_id: UUID | None = None
):
    # Recheck current notebook owner and membership; a stale/wrong link must never
    # give a teacher access to another student's or unrelated notebook's attempts.
    statement = (
        select(StudentAssignmentItem, Problem)
        .join(
            Problem,
            (StudentAssignmentItem.problem_id == Problem.id)
            & (StudentAssignmentItem.user_id == Problem.user_id),
        )
        .join(AssignmentItem, AssignmentItem.id == StudentAssignmentItem.item_id)
        .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
        .join(
            ClassMembership,
            (ClassMembership.class_id == Assignment.class_id)
            & (ClassMembership.user_id == StudentAssignmentItem.user_id),
        )
        .where(Assignment.id == assignment_id)
    )
    if user_id is not None:
        statement = statement.where(StudentAssignmentItem.user_id == user_id)
    return session.exec(statement).all()


def _linked_attempts(
    session: Session, assignment_id: UUID, user_id: UUID | None = None
) -> list[tuple[UUID, Attempt]]:
    statement = (
        select(StudentAssignmentItem.item_id, Attempt)
        .join(
            Problem,
            (StudentAssignmentItem.problem_id == Problem.id)
            & (StudentAssignmentItem.user_id == Problem.user_id),
        )
        .join(
            Attempt,
            (Attempt.problem_id == Problem.id) & (Attempt.user_id == Problem.user_id),
        )
        .join(AssignmentItem, AssignmentItem.id == StudentAssignmentItem.item_id)
        .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
        .join(
            ClassMembership,
            (ClassMembership.class_id == Assignment.class_id)
            & (ClassMembership.user_id == StudentAssignmentItem.user_id),
        )
        .join(User, User.id == StudentAssignmentItem.user_id)
        .where(Assignment.id == assignment_id, User.is_active == True)
        .order_by(Attempt.created_at, Attempt.id)
    )
    if user_id is not None:
        statement = statement.where(StudentAssignmentItem.user_id == user_id)
    return list(session.exec(statement).all())


@router.get("/teacher/classes", response_model=list[ClassResponse])
def list_teacher_classes(
    session: Session = Depends(get_session), teacher: User = Depends(get_teacher)
):
    classrooms = session.exec(
        select(Classroom)
        .where(Classroom.teacher_id == teacher.id)
        .order_by(Classroom.created_at.desc(), Classroom.id)
    ).all()
    return [_class_response(session, classroom) for classroom in classrooms]


@router.post("/teacher/classes", response_model=ClassResponse)
def create_class(
    payload: ClassCreateRequest,
    session: Session = Depends(get_session),
    teacher: User = Depends(get_teacher),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Class name must not be empty")
    for _ in range(3):
        classroom = Classroom(
            teacher_id=teacher.id,
            name=name,
            join_code="".join(
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10)
            ),
        )
        session.add(classroom)
        try:
            session.commit()
            return _class_response(session, classroom)
        except IntegrityError:
            session.rollback()
    raise HTTPException(
        status_code=503, detail="Could not generate a class code. Please try again."
    )


@router.get(
    "/teacher/classes/{class_id}/assignments", response_model=list[AssignmentSummary]
)
def list_class_assignments(
    class_id: UUID,
    session: Session = Depends(get_session),
    teacher: User = Depends(get_teacher),
):
    classroom = _owned_class(session, class_id, teacher)
    assignments = session.exec(
        select(Assignment)
        .where(Assignment.class_id == class_id)
        .order_by(Assignment.created_at.desc(), Assignment.id)
    ).all()
    return [_summary(session, assignment, classroom) for assignment in assignments]


async def _validated_images(images: list[UploadFile]) -> list[bytes]:
    if not 1 <= len(images) <= MAX_IMAGES:
        raise HTTPException(
            status_code=422, detail=f"Upload between 1 and {MAX_IMAGES} images"
        )
    total = 0
    validated = []
    for upload in images:
        data = await upload.read(MAX_FILE_BYTES + 1)
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Images must be at most 7 MB each and 30 MB in total",
            )
        try:
            with Image.open(BytesIO(data)) as source:
                if (
                    source.format not in {"PNG", "JPEG", "WEBP"}
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise ValueError(
                        "Only single-page PNG, JPEG and WebP images are supported"
                    )
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise HTTPException(
                        status_code=413,
                        detail="Each image must contain at most 16 million pixels",
                    )
                source.verify()
            with Image.open(BytesIO(data)) as source:
                # Preserve dark handwriting from transparent PNGs when flattening
                # to JPEG, including grayscale-alpha and palette transparency.
                with ImageOps.exif_transpose(source).convert("RGBA") as foreground:
                    with Image.new("RGB", foreground.size, "white") as normalized:
                        normalized.paste(foreground, mask=foreground.getchannel("A"))
                        output = BytesIO()
                        normalized.save(output, format="JPEG", quality=95)
                        validated.append(output.getvalue())
        except HTTPException:
            raise
        except (
            ValueError,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ) as exc:
            raise HTTPException(
                status_code=422,
                detail="Every exercise must be a valid PNG, JPEG or WebP image",
            ) from exc
    return validated


@router.post(
    "/teacher/classes/{class_id}/assignments", response_model=AssignmentSummary
)
async def create_assignment(
    class_id: UUID,
    title: str = Form(..., min_length=1, max_length=255),
    images: list[UploadFile] = File(...),
    allow_reveal: bool = Form(True),
    session: Session = Depends(get_session),
    teacher: User = Depends(get_teacher),
):
    classroom = _owned_class(session, class_id, teacher)
    title = title.strip()
    if not title:
        raise HTTPException(
            status_code=422, detail="Assignment title must not be empty"
        )
    validated = await _validated_images(images)
    assignment = Assignment(class_id=class_id, title=title, allow_reveal=allow_reveal)
    items = [
        AssignmentItem(
            assignment_id=assignment.id,
            title=f"{title[:249]} · {position + 1}",
            position=position,
            image_key=f"classes/{class_id}/assignments/{assignment.id}/{position}.jpg",
        )
        for position in range(len(validated))
    ]
    uploaded = []
    try:
        # Configuration checks happen before writing the first artifact.
        _asset_url(items[0].image_key)
        for item, data in zip(items, validated):
            uploaded.append(item.image_key)
            upload_bytes(key=item.image_key, data=data, content_type="image/jpeg")
        session.add(assignment)
        session.flush()
        session.add_all(items)
        session.commit()
    except Exception as exc:
        session.rollback()
        for key in uploaded:
            try:
                delete_bytes(key=key)
            except Exception:
                logger.exception("Could not clean up an unpublished assignment image")
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, R2ConfigurationError):
            raise HTTPException(
                status_code=503, detail=f"Artifact storage is not configured: {exc}"
            ) from exc
        logger.exception("Could not publish assignment")
        raise HTTPException(
            status_code=502, detail="Could not save the assignment. Please try again."
        ) from exc
    return _summary(session, assignment, classroom, items)


@router.patch("/teacher/assignments/{assignment_id}", response_model=AssignmentSummary)
def update_assignment_policy(
    assignment_id: UUID,
    payload: AssignmentPolicyUpdate,
    session: Session = Depends(get_session),
    teacher: User = Depends(get_teacher),
):
    assignment, classroom = _owned_assignment(session, assignment_id, teacher)
    assignment.allow_reveal = payload.allow_reveal
    session.add(assignment)
    session.commit()
    return _summary(session, assignment, classroom)


@router.get("/teacher/assignments/{assignment_id}", response_model=AssignmentDetail)
def assignment_detail(
    assignment_id: UUID,
    session: Session = Depends(get_session),
    teacher: User = Depends(get_teacher),
):
    assignment, classroom = _owned_assignment(session, assignment_id, teacher)
    items = _items(session, assignment.id)
    rows = _linked_attempts(session, assignment_id)
    per_student = defaultdict(list)
    for item_id, attempt in rows:
        per_student[attempt.user_id].append((item_id, attempt))
    students = []
    for student in _members(session, classroom.id):
        attempts = per_student[student.id]
        completed = set()
        attention = {}
        for item_id, attempt in attempts:
            if attempt.verdict in ATTENTION_VERDICTS:
                attention[item_id] = True
            if attempt.mode == "check_solution":
                if attempt.verdict in COMPLETED_VERDICTS:
                    completed.add(item_id)
                if attempt.verdict in COMPLETED_VERDICTS | {"correct_so_far"}:
                    attention[item_id] = False
        students.append(
            StudentProgress(
                id=student.id,
                full_name=student.full_name,
                completed_count=len(completed),
                attempt_count=len(attempts),
                hint_count=sum(attempt.mode == "hint" for _, attempt in attempts),
                needs_attention=any(attention.values()),
                last_activity=max(
                    (_utc(attempt.created_at) for _, attempt in attempts), default=None
                ),
            )
        )
    errors = Counter()
    attempt_users = {attempt.id: attempt.user_id for _, attempt in rows}
    if attempt_users:
        for error in session.exec(
            select(ErrorEvent).where(ErrorEvent.attempt_id.in_(attempt_users))
        ).all():
            if (
                error.user_id == attempt_users[error.attempt_id]
                and error.error_type
                and error.error_type not in {"none", "unknown"}
            ):
                errors[error.error_type] += 1
    return AssignmentDetail(
        assignment=_summary(session, assignment, classroom, items),
        items=[_item_response(item) for item in items],
        students=students,
        common_errors=[
            CommonError(error_type=error, count=count)
            for error, count in sorted(
                errors.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
    )


@router.get(
    "/teacher/assignments/{assignment_id}/students/{user_id}",
    response_model=StudentWorkResponse,
)
def inspect_student_work(
    assignment_id: UUID,
    user_id: UUID,
    session: Session = Depends(get_session),
    teacher: User = Depends(get_teacher),
):
    assignment, classroom = _owned_assignment(session, assignment_id, teacher)
    student = next(
        (
            student
            for student in _members(session, classroom.id)
            if student.id == user_id
        ),
        None,
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found in this class")
    items = _items(session, assignment_id)
    problems = {
        link.item_id: problem.id
        for link, problem in _linked_problems(session, assignment_id, user_id)
    }
    attempts = defaultdict(list)
    for item_id, attempt in _linked_attempts(session, assignment_id, user_id):
        page_keys = (
            attempt.solution_page_keys
            if isinstance(attempt.solution_page_keys, list)
            else []
        )
        attempts[item_id].append(
            ClassroomAttemptResponse(
                id=attempt.id,
                mode=attempt.mode,
                verdict=attempt.verdict,
                response_type=attempt.response_type,
                message_is=attempt.message_is,
                created_at=_utc(attempt.created_at),
                solution_image_url=_asset_url(attempt.solution_image_key),
                solution_page_urls=[
                    _asset_url(key) for key in page_keys if isinstance(key, str) and key
                ],
            )
        )
    return StudentWorkResponse(
        student=StudentIdentity(id=student.id, full_name=student.full_name),
        assignment=_summary(session, assignment, classroom, items),
        items=[
            StudentWorkItem(
                **_item_response(item).model_dump(),
                problem_id=problems.get(item.id),
                attempts=attempts[item.id],
            )
            for item in items
        ],
    )


@router.post("/student/classes/join", response_model=ClassResponse)
def join_class(
    payload: JoinClassRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    classroom = session.exec(
        select(Classroom).where(
            Classroom.join_code == payload.join_code.strip().upper()
        )
    ).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class code not found")
    if not session.get(ClassMembership, (classroom.id, user.id)):
        session.add(ClassMembership(class_id=classroom.id, user_id=user.id))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if not session.get(ClassMembership, (classroom.id, user.id)):
                raise
    return _class_response(session, classroom)


@router.get("/student/classes", response_model=list[ClassResponse])
def list_student_classes(
    session: Session = Depends(get_session), user: User = Depends(get_current_user)
):
    classrooms = session.exec(
        select(Classroom)
        .join(ClassMembership, ClassMembership.class_id == Classroom.id)
        .where(ClassMembership.user_id == user.id)
        .order_by(Classroom.created_at.desc(), Classroom.id)
    ).all()
    return [_class_response(session, classroom) for classroom in classrooms]


@router.get("/student/assignments", response_model=list[StudentAssignmentResponse])
def list_student_assignments(
    session: Session = Depends(get_session), user: User = Depends(get_current_user)
):
    rows = session.exec(
        select(Assignment, Classroom)
        .join(Classroom, Classroom.id == Assignment.class_id)
        .join(ClassMembership, ClassMembership.class_id == Classroom.id)
        .where(ClassMembership.user_id == user.id)
        .order_by(Assignment.created_at.desc(), Assignment.id)
    ).all()
    result = []
    for assignment, classroom in rows:
        items = _items(session, assignment.id)
        problems = {
            link.item_id: problem.id
            for link, problem in _linked_problems(session, assignment.id, user.id)
        }
        result.append(
            StudentAssignmentResponse(
                **_summary(session, assignment, classroom, items).model_dump(),
                items=[
                    StudentAssignmentItemResponse(
                        **_item_response(item).model_dump(),
                        problem_id=problems.get(item.id),
                    )
                    for item in items
                ],
            )
        )
    return result


@router.post(
    "/student/assignments/{assignment_id}/items/{item_id}/start",
    response_model=StartItemResponse,
)
def start_assignment_item(
    assignment_id: UUID,
    item_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    row = session.exec(
        select(Assignment, AssignmentItem)
        .join(AssignmentItem, AssignmentItem.assignment_id == Assignment.id)
        .join(ClassMembership, ClassMembership.class_id == Assignment.class_id)
        .where(
            Assignment.id == assignment_id,
            AssignmentItem.id == item_id,
            ClassMembership.user_id == user.id,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment item not found")
    assignment, item = row
    image_url = _asset_url(item.image_key)
    # PostgreSQL serializes starts for a member here. SQLite ignores row locks,
    # so the conditional link claim below is also required for notebook restarts.
    session.exec(
        select(ClassMembership)
        .where(
            ClassMembership.class_id == assignment.class_id,
            ClassMembership.user_id == user.id,
        )
        .with_for_update()
    ).first()
    statement = select(StudentAssignmentItem).where(
        StudentAssignmentItem.item_id == item.id,
        StudentAssignmentItem.user_id == user.id,
    )
    link = session.exec(statement).first()
    problem = (
        session.get(Problem, link.problem_id) if link and link.problem_id else None
    )
    if problem is not None and problem.user_id != user.id:
        problem = None
    if problem is None:
        folder = _ensure_default_folder(session=session, user_id=user.id)
        problem = Problem(user_id=user.id, folder_id=folder.id, title=item.title)
        try:
            session.add(problem)
            session.flush()
            if link is None:
                session.add(
                    StudentAssignmentItem(
                        item_id=item.id, user_id=user.id, problem_id=problem.id
                    )
                )
                session.commit()
            else:
                claimed = session.execute(
                    update(StudentAssignmentItem)
                    .where(
                        StudentAssignmentItem.id == link.id,
                        StudentAssignmentItem.problem_id == link.problem_id,
                    )
                    .values(problem_id=problem.id)
                    .execution_options(synchronize_session=False)
                ).rowcount
                if claimed == 1:
                    session.commit()
                else:
                    # Another request replaced the stale/cleared link first.
                    # Roll back this transaction's notebook before loading theirs.
                    session.rollback()
                    problem = None
        except IntegrityError:
            session.rollback()
            problem = None
        if problem is None:
            link = session.exec(statement).first()
            problem = (
                session.get(Problem, link.problem_id)
                if link and link.problem_id
                else None
            )
            if problem is None or problem.user_id != user.id:
                raise HTTPException(
                    status_code=409,
                    detail="The notebook changed. Please open the exercise again.",
                )
    folder = session.get(Folder, problem.folder_id) if problem.folder_id else None
    return StartItemResponse(
        problem=_problem_response(
            problem,
            folder.name if folder and folder.user_id == user.id else None,
            session=session,
        ),
        image_url=image_url,
    )
