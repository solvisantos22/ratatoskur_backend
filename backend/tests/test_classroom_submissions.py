from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from importlib import import_module
from threading import Barrier
from uuid import UUID, uuid4
import asyncio

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from PIL import Image
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine, select
from starlette.datastructures import UploadFile

from backend.models.auth_models import AnalyticsEvent, Attempt, ErrorEvent, Problem, User
from backend.models.classroom_models import ClassMembership, StudentAssignmentItem
from backend.tests.test_classrooms import auth, classroom_api, png, setup_assignment, start, add_attempt


def page(color="white"):
    output = BytesIO()
    Image.new("RGBA", (24, 24), color).save(output, format="PNG")
    return output.getvalue()


def submit(api, assignment, item, problem_id, submission_id=None, pages=None, name="student"):
    client, _, users, _ = api
    return client.post(
        f"/student/assignments/{assignment['id']}/items/{item['id']}/submissions",
        headers=auth(users, name),
        data={"problem_id": problem_id, "submission_id": str(submission_id or uuid4())},
        files=[("solution_pages", (f"page-{i}.png", value, "image/png"))
               for i, value in enumerate([png()] if pages is None else pages)],
    )


def inspection(api, assignment, name="teacher"):
    client, _, users, _ = api
    return client.get(f"/teacher/assignments/{assignment['id']}/students/{users['student'].id}",
                      headers=auth(users, name))


def test_submit_without_ai_returns_committed_private_ordered_snapshot(classroom_api, monkeypatch):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    opened = start(classroom_api, assignment, items[0]).json()
    assert opened.get("last_submission") is None
    before_events = len(session.exec(select(AnalyticsEvent)).all())
    monkeypatch.setenv("GEMINI_API_KEY", "")
    def forbidden(**kwargs):
        pytest.fail("A manual submission must never call AI")
    monkeypatch.setattr("backend.routes.query.call_mode_v3_with_retry", forbidden)
    submission_id = uuid4()
    result = submit(classroom_api, assignment, items[0], opened["problem"]["id"], submission_id,
                    pages=[page("black"), page((0, 0, 0, 0))])
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert set(receipt) == {"id", "created_at", "page_count"}
    assert receipt["id"] == str(submission_id)
    assert receipt["page_count"] == 2
    assert receipt["created_at"].endswith("Z")
    from backend.models.classroom_models import ClassroomSubmission
    with Session(session.get_bind()) as committed:
        assert committed.get(ClassroomSubmission, submission_id) is not None
    assert session.exec(select(Attempt)).all() == []
    assert session.exec(select(ErrorEvent)).all() == []
    assert len(session.exec(select(AnalyticsEvent)).all()) == before_events
    work = inspection(classroom_api, assignment).json()["items"][0]
    assert work["attempts"] == []
    assert len(work["submissions"]) == 1
    snapshot = work["submissions"][0]
    assert {key: snapshot[key] for key in receipt} == receipt
    for url, expected in zip(snapshot["solution_page_urls"], [0, 255]):
        image_response = client.get(url)
        with Image.open(BytesIO(image_response.content)) as image:
            assert image.format == "JPEG"
            assert image.getpixel((12, 12)) == (expected,) * 3
        assert client.get(url.split("?")[0]).status_code in {403, 422}
    assert start(classroom_api, assignment, items[0]).json()["last_submission"] == receipt
    listing = client.get("/student/assignments", headers=auth(users, "student")).json()[0]
    assert listing["items"][0]["last_submitted_at"] == receipt["created_at"]
    detail = client.get(f"/teacher/assignments/{assignment['id']}", headers=auth(users, "teacher")).json()
    progress = detail["students"][0]
    assert progress["submission_count"] == progress["submitted_item_count"] == 1
    assert progress["last_activity"] == receipt["created_at"]
    assert progress["completed_count"] == progress["attempt_count"] == progress["hint_count"] == 0
    assert progress["needs_attention"] is False
    assert detail["common_errors"] == []


def test_retry_conflict_and_deliberate_resubmission_keep_original_snapshot(classroom_api):
    _, session, _, root = classroom_api
    _, assignment, items = setup_assignment(classroom_api)
    first_problem = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    second_problem = start(classroom_api, assignment, items[1]).json()["problem"]["id"]
    retry_id = uuid4()
    first = submit(classroom_api, assignment, items[0], first_problem, retry_id, [page("black"), page()])
    assert first.status_code == 200, first.text
    original_artifacts = sorted((root / "artifacts").rglob("*.jpg"))
    assert submit(classroom_api, assignment, items[0], first_problem, retry_id, [page("black"), page()]).json() == first.json()
    assert sorted((root / "artifacts").rglob("*.jpg")) == original_artifacts
    assert submit(classroom_api, assignment, items[0], first_problem, retry_id, [page(), page("black")]).status_code == 409
    assert submit(classroom_api, assignment, items[1], second_problem, retry_id).status_code == 409
    second = submit(classroom_api, assignment, items[0], first_problem, pages=[page("red")])
    assert second.status_code == 200, second.text
    assert second.json()["id"] != first.json()["id"]
    assert [row["id"] for row in inspection(classroom_api, assignment).json()["items"][0]["submissions"]] == [first.json()["id"], second.json()["id"]]
    assert start(classroom_api, assignment, items[0]).json()["last_submission"] == second.json()
    assert all(path.exists() for path in original_artifacts)
    from backend.models.classroom_models import ClassroomSubmission
    assert len(session.exec(select(ClassroomSubmission)).all()) == 2


@pytest.mark.parametrize("case", ["outsider", "personal", "other_owner", "wrong_item", "stale", "inactive", "wrong_link"])
def test_submissions_require_current_member_and_exact_owned_notebook(classroom_api, case):
    _, session, users, root = classroom_api
    classroom, assignment, items = setup_assignment(classroom_api)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    name = "student"
    if case == "outsider":
        name = "outsider"
    elif case in {"personal", "other_owner", "wrong_link"}:
        other = Problem(user_id=users["outsider" if case != "personal" else "student"].id, title="Private")
        session.add(other)
        session.commit()
        problem_id = str(other.id)
        if case == "wrong_link":
            link = session.exec(select(StudentAssignmentItem)).one()
            link.problem_id = other.id
            session.add(link)
            session.commit()
    elif case == "wrong_item":
        problem_id = start(classroom_api, assignment, items[1]).json()["problem"]["id"]
    elif case == "stale":
        session.delete(session.get(ClassMembership, (UUID(classroom["id"]), users["student"].id)))
        session.commit()
    elif case == "inactive":
        users["student"].is_active = False
        session.add(users["student"])
        session.commit()
    before = list((root / "artifacts").rglob("*.jpg"))
    response = submit(classroom_api, assignment, items[0], problem_id, name=name)
    assert response.status_code in {401, 404}, response.text
    assert list((root / "artifacts").rglob("*.jpg")) == before


@pytest.mark.parametrize("pages, expected", [([], 422), ([b"not an image"], 422), ([png()] * 13, 422), ([b"x" * (7 * 1024 * 1024 + 1)], 413)])
def test_submission_page_validation_is_atomic(classroom_api, pages, expected):
    _, _, _, root = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    before = list((root / "artifacts").rglob("*.jpg"))
    response = submit(classroom_api, assignment, items[0], problem_id, pages=pages)
    assert response.status_code == expected, response.text
    assert list((root / "artifacts").rglob("*.jpg")) == before
    assert inspection(classroom_api, assignment).json()["items"][0]["submissions"] == []


@pytest.mark.parametrize("limit, value, pages", [("MAX_TOTAL_BYTES", len(png()) + 1, [png()] * 2), ("MAX_IMAGE_PIXELS", 400, [png()])])
def test_submission_total_and_pixel_limits(classroom_api, monkeypatch, limit, value, pages):
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    monkeypatch.setattr(f"backend.routes.classroom.{limit}", value)
    response = submit(classroom_api, assignment, items[0], problem_id, pages=pages)
    assert response.status_code == 413, response.text
    assert inspection(classroom_api, assignment).json()["items"][0]["submissions"] == []


def test_storage_failure_cleans_partial_submission_and_allows_same_retry(classroom_api, monkeypatch):
    from backend.storage.r2 import upload_bytes
    _, _, _, root = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    before = list((root / "artifacts").rglob("*.jpg"))
    calls = 0
    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        upload_bytes(**kwargs)
        if calls == 2:
            raise OSError("Connection lost after write")
    monkeypatch.setattr("backend.routes.classroom.upload_bytes", fail_second)
    retry_id = uuid4()
    response = submit(classroom_api, assignment, items[0], problem_id, retry_id, [png()] * 2)
    assert response.status_code == 502, response.text
    assert list((root / "artifacts").rglob("*.jpg")) == before
    assert inspection(classroom_api, assignment).json()["items"][0]["submissions"] == []
    monkeypatch.setattr("backend.routes.classroom.upload_bytes", upload_bytes)
    assert submit(classroom_api, assignment, items[0], problem_id, retry_id, [png()] * 2).status_code == 200


def test_teacher_submission_access_rechecks_link_membership_and_account(classroom_api):
    client, session, users, _ = classroom_api
    classroom, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    response = submit(classroom_api, assignment, items[0], problem_id)
    assert response.status_code == 200, response.text
    assert inspection(classroom_api, assignment, "other").status_code == 404
    assert inspection(classroom_api, assignment, "student").status_code == 403
    link = session.exec(select(StudentAssignmentItem)).one()
    private = Problem(user_id=users["outsider"].id, title="Other notebook")
    session.add(private)
    session.commit()
    link.problem_id = private.id
    session.add(link)
    session.commit()
    assert inspection(classroom_api, assignment).json()["items"][0]["submissions"] == []
    detail_url = f"/teacher/assignments/{assignment['id']}"
    assert client.get(detail_url, headers=auth(users, "teacher")).json()["students"][0]["submission_count"] == 0
    link.problem_id = UUID(problem_id)
    session.add(link)
    users["student"].is_active = False
    session.add(users["student"])
    session.commit()
    assert inspection(classroom_api, assignment).status_code == 404
    users["student"].is_active = True
    session.add(users["student"])
    session.delete(session.get(ClassMembership, (UUID(classroom["id"]), users["student"].id)))
    session.commit()
    assert inspection(classroom_api, assignment).status_code == 404


def test_submission_counts_keep_ai_progress_separate(classroom_api):
    client, _, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api)
    first = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    second = start(classroom_api, assignment, items[1]).json()["problem"]["id"]
    add_attempt(classroom_api, first, verdict="fully_solved")
    add_attempt(classroom_api, second, mode="hint", minute=1)
    for problem_id, item in [(first, items[0]), (first, items[0]), (second, items[1])]:
        response = submit(classroom_api, assignment, item, problem_id)
        assert response.status_code == 200, response.text
    progress = client.get(f"/teacher/assignments/{assignment['id']}", headers=auth(users, "teacher")).json()["students"][0]
    assert progress["submission_count"] == 3
    assert progress["submitted_item_count"] == 2
    assert progress["completed_count"] == 1
    assert progress["attempt_count"] == 2
    assert progress["hint_count"] == 1
    assert progress["needs_attention"] is True
    assert datetime.fromisoformat(progress["last_activity"].replace("Z", "+00:00")) > datetime.now(timezone.utc)


def test_deleting_notebook_preserves_snapshot_without_exposing_it_in_restart(classroom_api):
    client, session, users, root = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    response = submit(classroom_api, assignment, items[0], problem_id)
    assert response.status_code == 200, response.text
    before = list((root / "artifacts").rglob("*.jpg"))
    deleted = client.delete(f"/problems/{problem_id}", headers=auth(users, "student"))
    assert deleted.status_code == 200, deleted.text
    assert inspection(classroom_api, assignment).json()["items"][0]["submissions"] == []
    restarted = start(classroom_api, assignment, items[0]).json()
    assert restarted["last_submission"] is None
    assert restarted["problem"]["id"] != problem_id
    assert submit(classroom_api, assignment, items[0], problem_id).status_code == 404
    from backend.models.classroom_models import ClassroomSubmission
    assert session.get(ClassroomSubmission, UUID(response.json()["id"])) is not None
    assert all(path.exists() for path in before)


def test_concurrent_identical_retry_keeps_one_snapshot_and_its_artifacts(classroom_api, monkeypatch):
    from backend.routes import classroom
    from backend.storage.r2 import upload_bytes
    _, session, users, root = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = UUID(start(classroom_api, assignment, items[0]).json()["problem"]["id"])
    submission_id = uuid4()
    student_id = users["student"].id
    barrier = Barrier(2)
    def concurrent_upload(**kwargs):
        barrier.wait(timeout=10)
        return upload_bytes(**kwargs)
    monkeypatch.setattr(classroom, "upload_bytes", concurrent_upload)
    def request(_):
        with Session(session.get_bind()) as request_session:
            return asyncio.run(classroom.submit_assignment_item(
                assignment_id=UUID(assignment["id"]), item_id=UUID(items[0]["id"]),
                problem_id=problem_id, submission_id=submission_id,
                solution_pages=[UploadFile(filename="page.png", file=BytesIO(png()))],
                session=request_session, user=request_session.get(User, student_id),
            )).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(request, range(2)))
    assert receipts[0] == receipts[1]
    session.expire_all()
    from backend.models.classroom_models import ClassroomSubmission
    assert len(session.exec(select(ClassroomSubmission)).all()) == 1
    assert len(list((root / "artifacts").rglob("*.jpg"))) == 2
    urls = inspection(classroom_api, assignment).json()["items"][0]["submissions"][0]["solution_page_urls"]
    assert len(urls) == 1
    assert classroom_api[0].get(urls[0]).status_code == 200


def test_error_after_commit_does_not_delete_committed_submission(classroom_api, monkeypatch):
    _, session, _, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    original_commit = session.commit
    def commit_then_disconnect():
        original_commit()
        raise OSError("Commit succeeded but response was lost")
    monkeypatch.setattr(session, "commit", commit_then_disconnect)
    response = submit(classroom_api, assignment, items[0], problem_id)
    assert response.status_code == 200, response.text
    urls = inspection(classroom_api, assignment).json()["items"][0]["submissions"][0]["solution_page_urls"]
    assert classroom_api[0].get(urls[0]).status_code == 200


def test_submission_migration_is_additive_and_based_on_current_head(tmp_path):
    migration = import_module("backend.alembic.versions.b3c8d2e1f6a9_add_classroom_submissions")
    assert migration.down_revision == "e6a195922bd4"
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    SQLModel.metadata.create_all(engine, tables=[t for t in SQLModel.metadata.sorted_tables if t.name != "classroom_submissions"])
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO assignments (id, class_id, title, allow_reveal, created_at) VALUES ('old', 'class', 'Keep my class', 0, CURRENT_TIMESTAMP)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {c["name"] for c in inspect(connection).get_columns("classroom_submissions")} == set(SQLModel.metadata.tables["classroom_submissions"].columns.keys())
            assert connection.execute(text("SELECT title, allow_reveal FROM assignments")).one() == ("Keep my class", 0)
            migration.downgrade()
            assert "classroom_submissions" not in inspect(connection).get_table_names()
            assert connection.execute(text("SELECT title FROM assignments")).scalar_one() == "Keep my class"
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert "CREATE TABLE classroom_submissions" in output.getvalue()
    assert "DROP TABLE" not in output.getvalue()
    engine.dispose()


@pytest.mark.parametrize("old_policy", [False, True])
def test_local_setup_adds_submission_table_preserving_existing_data(tmp_path, old_policy):
    from scripts.setup_local import initialize_local_database
    url = f"sqlite:///{tmp_path / 'local.db'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine, tables=[t for t in SQLModel.metadata.sorted_tables if t.name != "classroom_submissions"])
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO assignments (id, class_id, title, allow_reveal, created_at) VALUES ('old', 'class', 'Keep my work', 0, CURRENT_TIMESTAMP)"))
        if old_policy:
            connection.execute(text("ALTER TABLE assignments DROP COLUMN allow_reveal"))
    initialize_local_database(url)
    assert "classroom_submissions" in inspect(engine).get_table_names()
    initialize_local_database(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT title, allow_reveal FROM assignments")).one() == ("Keep my work", int(old_policy))
    engine.dispose()


def test_local_setup_rejects_unknown_damage_before_adding_submission_table(tmp_path):
    from scripts.setup_local import initialize_local_database
    url = f"sqlite:///{tmp_path / 'damaged.db'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine, tables=[t for t in SQLModel.metadata.sorted_tables if t.name != "classroom_submissions"])
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE assignments DROP COLUMN title"))
    with pytest.raises(ValueError, match="different schema"):
        initialize_local_database(url)
    assert "classroom_submissions" not in inspect(engine).get_table_names()
    engine.dispose()


def test_upload_reads_finish_before_narrow_postgres_locks_and_retry_releases_them(classroom_api, monkeypatch):
    """A spooled file yields to a worker; no DB row lock may cross that yield."""
    from sqlalchemy.dialects import postgresql
    from backend.routes import classroom
    _, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = UUID(start(classroom_api, assignment, items[0]).json()["problem"]["id"])
    student_id = users["student"].id
    submission_id = uuid4()
    events = []
    original_exec = session.exec
    def record_lock(statement, *args, **kwargs):
        if getattr(statement, "_for_update_arg", None) is not None:
            events.append(("lock", str(statement.compile(dialect=postgresql.dialect()))))
        return original_exec(statement, *args, **kwargs)
    monkeypatch.setattr(session, "exec", record_lock)
    class YieldingUpload(UploadFile):
        async def read(self, size=-1):
            assert not any(kind == "lock" for kind, _ in events), "A row lock is held across an awaited file read"
            events.append(("read", None))
            await asyncio.sleep(0)
            return await super().read(size)
    def request():
        return asyncio.run(classroom.submit_assignment_item(
            assignment_id=UUID(assignment["id"]), item_id=UUID(items[0]["id"]),
            problem_id=problem_id, submission_id=submission_id,
            solution_pages=[YieldingUpload(filename="page.png", file=BytesIO(png()))],
            session=session, user=session.get(User, student_id),
        ))
    receipt = request()
    assert [kind for kind, _ in events] == ["read", "lock"]
    lock_sql = next(sql for kind, sql in events if kind == "lock")
    locked_tables = set(lock_sql.split("FOR UPDATE OF ")[1].split(", "))
    assert locked_tables == {"student_assignment_items", "problems", "class_memberships", "users"}
    assert not session.in_transaction(), "A committed response must release its transaction"
    events.clear()
    assert request() == receipt
    assert not session.in_transaction(), "An idempotent response must release its row locks before returning"
