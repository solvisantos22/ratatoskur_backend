from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.auth.deps import get_current_user
from backend.db import get_session
from backend.error_taxonomy import CANONICAL_ERROR_TYPES, normalize_error_type
from backend.exam_service import choose_auto_targets, extract_answer_text_from_image, generate_exam_items, grade_answer
from backend.models.auth_models import (
    ErrorBankEntry,
    ExamPack,
    ExamPackItem,
    ExamSession,
    ExamSessionAnswer,
    User,
)
from backend.schemas.exam import (
    BUILD_MODES,
    FEEDBACK_MODES,
    PACK_SIZES,
    TOPICS,
    ExamAnswerUpdateRequest,
    ExamAnswerUpdateResponse,
    ExamPackCreateRequest,
    ExamPackDetailResponse,
    ExamPackItemResponse,
    ExamPackResponse,
    ExamSessionResultItemResponse,
    ExamSessionResultsResponse,
    ExamSessionStartResponse,
    ExamSessionSubmitResponse,
)

router = APIRouter(tags=["exam"])


def _normalize_pack_input(payload: ExamPackCreateRequest) -> tuple[list[str], list[str]]:
    if payload.pack_size not in PACK_SIZES:
        raise HTTPException(status_code=422, detail="pack_size must be one of 10, 20, 30")
    if payload.build_mode not in BUILD_MODES:
        raise HTTPException(status_code=422, detail="build_mode must be auto or manual")
    if payload.feedback_mode not in FEEDBACK_MODES:
        raise HTTPException(status_code=422, detail="feedback_mode must be per_question or end_exam")

    normalized_topics = list(dict.fromkeys(topic.strip().lower() for topic in payload.topics if topic.strip()))
    if not normalized_topics:
        normalized_topics = ["algebra", "fractions"]
    for topic in normalized_topics:
        if topic not in TOPICS:
            raise HTTPException(status_code=422, detail=f"unsupported topic: {topic}")

    manual_targets: list[str] = []
    for raw_target in payload.manual_error_targets or []:
        canonical = normalize_error_type(raw_target)
        if canonical and canonical not in manual_targets:
            manual_targets.append(canonical)
        elif raw_target.strip():
            raise HTTPException(status_code=422, detail=f"unsupported manual error target: {raw_target}")
    return normalized_topics, manual_targets


def _to_pack_response(pack: ExamPack) -> ExamPackResponse:
    return ExamPackResponse(
        id=pack.id,
        title=pack.title,
        pack_size=pack.pack_size,
        build_mode=pack.build_mode,
        feedback_mode=pack.feedback_mode,
        topics=pack.topics_json or [],
        manual_error_targets=pack.manual_error_targets_json,
        status=pack.status,
        generation_model=pack.generation_model,
        generation_prompt_version=pack.generation_prompt_version,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


def _to_pack_item_response(item: ExamPackItem) -> ExamPackItemResponse:
    return ExamPackItemResponse(
        id=item.id,
        position=item.position,
        topic=item.topic,
        difficulty=item.difficulty,
        target_error_type=item.target_error_type,
        target_concept_tag=item.target_concept_tag,
        question_text=item.question_text,
        answer_format=item.answer_format,
    )


def _load_pack_or_404(*, session: Session, pack_id: UUID, user: User) -> ExamPack:
    pack = session.exec(select(ExamPack).where(ExamPack.id == pack_id, ExamPack.user_id == user.id)).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Exam pack not found")
    return pack


def _load_session_or_404(*, session: Session, session_id: UUID, user: User) -> tuple[ExamSession, ExamPack]:
    exam_session = session.exec(
        select(ExamSession).where(ExamSession.id == session_id, ExamSession.user_id == user.id)
    ).first()
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")

    pack = session.exec(select(ExamPack).where(ExamPack.id == exam_session.pack_id, ExamPack.user_id == user.id)).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Exam pack not found")
    return exam_session, pack


def _resolve_answer_text(
    *,
    payload: ExamAnswerUpdateRequest,
    item: ExamPackItem,
) -> str | None:
    if payload.answer_text is not None:
        normalized = payload.answer_text.strip()
        if normalized:
            return normalized

    if payload.answer_image_base64 is None:
        return None

    try:
        extracted = extract_answer_text_from_image(
            answer_image_base64=payload.answer_image_base64,
            question_text=item.question_text,
            answer_format=item.answer_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to read handwritten answer: {exc}") from exc

    if extracted is None:
        raise HTTPException(
            status_code=422,
            detail="Could not read a final answer from handwriting. Please write the final answer clearly and retry.",
        )
    return extracted


@router.post("/exam-packs", response_model=ExamPackDetailResponse)
def create_exam_pack(
    payload: ExamPackCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    normalized_topics, manual_targets = _normalize_pack_input(payload)
    selected_targets: list[str]
    if payload.build_mode == "manual":
        if not manual_targets:
            raise HTTPException(status_code=422, detail="manual_error_targets required for manual build mode")
        selected_targets = manual_targets
    else:
        error_rows = session.exec(
            select(ErrorBankEntry)
            .where(ErrorBankEntry.anon_user_id == user.anon_user_id)
            .order_by((ErrorBankEntry.count - ErrorBankEntry.fixed_count).desc(), ErrorBankEntry.count.desc())
        ).all()
        candidate_errors: list[str] = []
        for row in error_rows:
            canonical = normalize_error_type(row.error_type, concept_tag=row.concept_tag)
            if canonical:
                candidate_errors.append(canonical)
        selected_targets = choose_auto_targets(candidate_errors=candidate_errors, topics=normalized_topics)
    selected_targets = [target for target in selected_targets if target in CANONICAL_ERROR_TYPES]
    if not selected_targets:
        selected_targets = choose_auto_targets(candidate_errors=[], topics=normalized_topics)

    now = datetime.now(timezone.utc)
    pack = ExamPack(
        id=uuid4(),
        user_id=user.id,
        anon_user_id=user.anon_user_id,
        title=payload.title.strip(),
        pack_size=payload.pack_size,
        build_mode=payload.build_mode,
        feedback_mode=payload.feedback_mode,
        topics_json=normalized_topics,
        manual_error_targets_json=selected_targets if payload.build_mode == "manual" else None,
        status="ready",
        generation_model="template_v1",
        generation_prompt_version="exam/v1",
        created_at=now,
        updated_at=now,
    )
    session.add(pack)
    session.flush()

    generated_items = generate_exam_items(
        pack_size=payload.pack_size,
        topics=normalized_topics,
        target_errors=selected_targets,
        seed=hash(str(pack.id)) % 1000000,
    )

    for generated in generated_items:
        session.add(
            ExamPackItem(
                id=uuid4(),
                pack_id=pack.id,
                position=generated.position,
                topic=generated.topic,
                difficulty=generated.difficulty,
                target_error_type=generated.target_error_type,
                target_concept_tag=generated.target_concept_tag,
                question_text=generated.question_text,
                answer_format=generated.answer_format,
                correct_answer_json=generated.correct_answer_json,
                grading_rubric_json=generated.grading_rubric_json,
                validator_notes_json=generated.validator_notes_json,
                created_at=now,
            )
        )

    session.commit()
    session.refresh(pack)
    items = session.exec(
        select(ExamPackItem).where(ExamPackItem.pack_id == pack.id).order_by(ExamPackItem.position.asc())
    ).all()
    return ExamPackDetailResponse(**_to_pack_response(pack).model_dump(), items=[_to_pack_item_response(i) for i in items])


@router.get("/exam-packs", response_model=list[ExamPackResponse])
def list_exam_packs(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    packs = session.exec(
        select(ExamPack).where(ExamPack.user_id == user.id).order_by(ExamPack.created_at.desc()).limit(50)
    ).all()
    return [_to_pack_response(pack) for pack in packs]


@router.get("/exam-packs/{pack_id}", response_model=ExamPackDetailResponse)
def get_exam_pack(
    pack_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    pack = _load_pack_or_404(session=session, pack_id=pack_id, user=user)
    items = session.exec(
        select(ExamPackItem).where(ExamPackItem.pack_id == pack.id).order_by(ExamPackItem.position.asc())
    ).all()
    return ExamPackDetailResponse(**_to_pack_response(pack).model_dump(), items=[_to_pack_item_response(i) for i in items])


@router.post("/exam-packs/{pack_id}/start", response_model=ExamSessionStartResponse)
def start_exam_pack(
    pack_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    pack = _load_pack_or_404(session=session, pack_id=pack_id, user=user)
    if pack.status != "ready":
        raise HTTPException(status_code=409, detail="Exam pack is not ready")

    items = session.exec(
        select(ExamPackItem).where(ExamPackItem.pack_id == pack.id).order_by(ExamPackItem.position.asc())
    ).all()

    existing_session = session.exec(
        select(ExamSession)
        .where(
            ExamSession.pack_id == pack.id,
            ExamSession.user_id == user.id,
            ExamSession.status == "in_progress",
        )
        .order_by(ExamSession.started_at.desc())
    ).first()
    if existing_session:
        return ExamSessionStartResponse(
            session_id=existing_session.id,
            pack=ExamPackDetailResponse(
                **_to_pack_response(pack).model_dump(),
                items=[_to_pack_item_response(item) for item in items],
            ),
        )

    now = datetime.now(timezone.utc)
    exam_session = ExamSession(
        id=uuid4(),
        pack_id=pack.id,
        user_id=user.id,
        anon_user_id=user.anon_user_id,
        status="in_progress",
        started_at=now,
    )
    session.add(exam_session)
    session.flush()

    for item in items:
        session.add(
            ExamSessionAnswer(
                id=uuid4(),
                session_id=exam_session.id,
                pack_item_id=item.id,
                answer_text=None,
                is_correct=None,
                score=None,
                feedback_text=None,
                graded_at=None,
                updated_at=now,
            )
        )

    session.commit()
    return ExamSessionStartResponse(
        session_id=exam_session.id,
        pack=ExamPackDetailResponse(
            **_to_pack_response(pack).model_dump(),
            items=[_to_pack_item_response(item) for item in items],
        ),
    )


@router.patch("/exam-sessions/{session_id}/answers/{item_id}", response_model=ExamAnswerUpdateResponse)
def save_exam_answer(
    session_id: UUID,
    item_id: UUID,
    payload: ExamAnswerUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    exam_session, pack = _load_session_or_404(session=session, session_id=session_id, user=user)
    if exam_session.status != "in_progress":
        raise HTTPException(status_code=409, detail="Exam session is not in progress")

    answer_row = session.exec(
        select(ExamSessionAnswer).where(
            ExamSessionAnswer.session_id == exam_session.id,
            ExamSessionAnswer.pack_item_id == item_id,
        )
    ).first()
    if not answer_row:
        raise HTTPException(status_code=404, detail="Exam answer row not found")

    item = session.exec(
        select(ExamPackItem).where(ExamPackItem.id == item_id, ExamPackItem.pack_id == pack.id)
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Exam item not found")

    resolved_answer_text = _resolve_answer_text(payload=payload, item=item)
    answer_row.answer_text = resolved_answer_text
    answer_row.updated_at = datetime.now(timezone.utc)
    graded = False
    if pack.feedback_mode == "per_question":
        is_correct, score, feedback = grade_answer(
            answer_text=resolved_answer_text,
            answer_format=item.answer_format,
            correct_answer_json=item.correct_answer_json or {},
        )
        answer_row.is_correct = is_correct
        answer_row.score = score
        answer_row.feedback_text = feedback
        answer_row.graded_at = datetime.now(timezone.utc)
        answer_row.grading_model = "rule_grader_v1"
        answer_row.grading_prompt_version = "exam/grade/rule_v1"
        graded = True

    session.add(answer_row)
    session.commit()
    session.refresh(answer_row)

    return ExamAnswerUpdateResponse(
        session_id=exam_session.id,
        item_id=item.id,
        answer_text=answer_row.answer_text,
        is_correct=answer_row.is_correct,
        score=answer_row.score,
        feedback_text=answer_row.feedback_text,
        graded=graded,
    )


@router.post("/exam-sessions/{session_id}/submit", response_model=ExamSessionSubmitResponse)
def submit_exam_session(
    session_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    exam_session, pack = _load_session_or_404(session=session, session_id=session_id, user=user)
    if exam_session.status != "in_progress":
        raise HTTPException(status_code=409, detail="Exam session is already submitted")

    now = datetime.now(timezone.utc)
    answer_rows = session.exec(
        select(ExamSessionAnswer).where(ExamSessionAnswer.session_id == exam_session.id)
    ).all()
    item_map = {
        item.id: item
        for item in session.exec(select(ExamPackItem).where(ExamPackItem.pack_id == pack.id)).all()
    }

    correct_count = 0
    total_count = len(answer_rows)
    for answer_row in answer_rows:
        if answer_row.is_correct is None:
            item = item_map.get(answer_row.pack_item_id)
            if item:
                is_correct, score, feedback = grade_answer(
                    answer_text=answer_row.answer_text,
                    answer_format=item.answer_format,
                    correct_answer_json=item.correct_answer_json or {},
                )
                answer_row.is_correct = is_correct
                answer_row.score = score
                answer_row.feedback_text = feedback
                answer_row.graded_at = now
                answer_row.grading_model = "rule_grader_v1"
                answer_row.grading_prompt_version = "exam/grade/rule_v1"
                session.add(answer_row)
        if answer_row.is_correct:
            correct_count += 1

    percent = (float(correct_count) / float(total_count) * 100.0) if total_count else 0.0
    exam_session.status = "graded"
    exam_session.submitted_at = now
    exam_session.graded_at = now
    exam_session.score_correct = correct_count
    exam_session.score_total = total_count
    exam_session.score_percent = percent
    session.add(exam_session)
    session.commit()
    session.refresh(exam_session)

    return ExamSessionSubmitResponse(
        session_id=exam_session.id,
        status=exam_session.status,
        score_correct=correct_count,
        score_total=total_count,
        score_percent=percent,
    )


@router.get("/exam-sessions/{session_id}/results", response_model=ExamSessionResultsResponse)
def get_exam_session_results(
    session_id: UUID,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    exam_session, pack = _load_session_or_404(session=session, session_id=session_id, user=user)
    items = session.exec(
        select(ExamPackItem).where(ExamPackItem.pack_id == pack.id).order_by(ExamPackItem.position.asc())
    ).all()
    answer_rows = session.exec(
        select(ExamSessionAnswer).where(ExamSessionAnswer.session_id == exam_session.id)
    ).all()
    answer_by_item = {row.pack_item_id: row for row in answer_rows}

    result_items = []
    for item in items:
        answer_row = answer_by_item.get(item.id)
        result_items.append(
            ExamSessionResultItemResponse(
                item_id=item.id,
                position=item.position,
                topic=item.topic,
                difficulty=item.difficulty,
                target_error_type=item.target_error_type,
                question_text=item.question_text,
                answer_format=item.answer_format,
                answer_text=answer_row.answer_text if answer_row else None,
                is_correct=answer_row.is_correct if answer_row else None,
                score=answer_row.score if answer_row else None,
                feedback_text=answer_row.feedback_text if answer_row else None,
            )
        )

    return ExamSessionResultsResponse(
        session_id=exam_session.id,
        pack_id=pack.id,
        status=exam_session.status,
        feedback_mode=pack.feedback_mode,
        score_correct=exam_session.score_correct,
        score_total=exam_session.score_total,
        score_percent=exam_session.score_percent,
        started_at=exam_session.started_at,
        submitted_at=exam_session.submitted_at,
        graded_at=exam_session.graded_at,
        items=result_items,
    )
