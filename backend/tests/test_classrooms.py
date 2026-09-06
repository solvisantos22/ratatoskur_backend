from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from backend.auth.jwt import create_access_token
from backend.db import get_session
from backend.main import app
from backend.models.auth_models import Attempt, ErrorEvent, Problem, User


def png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (24, 24), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def classroom_api(tmp_path, monkeypatch):
    monkeypatch.setenv("TEACHER_EMAILS", "teacher@example.com,other@example.com")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv(
        "LOCAL_STORAGE_SIGNING_SECRET", "test-only-signing-secret-that-is-long-enough"
    )
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'classrooms.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        users = {}
        for name in ("teacher", "other", "student", "outsider"):
            user = User(
                email=f"{name}@example.com",
                full_name=name.title(),
                password_hash="unused",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            users[name] = user

        def get_test_session():
            yield session

        app.dependency_overrides[get_session] = get_test_session
        with TestClient(app) as client:
            yield client, session, users, tmp_path
        app.dependency_overrides.clear()
    engine.dispose()


def auth(users, name):
    return {"Authorization": f"Bearer {create_access_token(users[name].id)}"}


def setup_assignment(api, count=2):
    client, _, users, _ = api
    response = client.post(
        "/teacher/classes", json={"name": "Year 8"}, headers=auth(users, "teacher")
    )
    assert response.status_code == 200, response.text
    classroom = response.json()
    response = client.post(
        "/student/classes/join",
        json={"join_code": classroom["join_code"].lower()},
        headers=auth(users, "student"),
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/teacher/classes/{classroom['id']}/assignments",
        data={"title": "Linear equations"},
        files=[
            ("images", (f"exercise-{i}.png", png(), "image/png")) for i in range(count)
        ],
        headers=auth(users, "teacher"),
    )
    assert response.status_code == 200, response.text
    assignment = response.json()
    detail = client.get(
        f"/teacher/assignments/{assignment['id']}", headers=auth(users, "teacher")
    )
    assert detail.status_code == 200, detail.text
    return classroom, assignment, detail.json()["items"]


def start(api, assignment, item, name="student"):
    client, _, users, _ = api
    return client.post(
        f"/student/assignments/{assignment['id']}/items/{item['id']}/start",
        headers=auth(users, name),
    )


def add_attempt(
    api,
    problem_id,
    *,
    mode="check_solution",
    verdict="incorrect",
    minute=0,
    error=None,
    user_name="student",
):
    _, session, users, _ = api
    user = users[user_name]
    attempt = Attempt(
        problem_id=UUID(problem_id),
        user_id=user.id,
        anon_user_id=user.anon_user_id,
        mode=mode,
        verdict=verdict,
        response_type="feedback",
        message_is="Skoðaðu annað skrefið.",
        created_at=datetime.now(timezone.utc) + timedelta(minutes=minute),
    )
    session.add(attempt)
    session.flush()
    if error:
        session.add(
            ErrorEvent(attempt_id=attempt.id, user_id=user.id, error_type=error)
        )
    session.commit()
    return attempt


def test_teacher_auth_allowlist_and_ownership(classroom_api):
    client, _, users, _ = classroom_api
    assert client.get("/teacher/classes").status_code == 401
    assert (
        client.get("/teacher/classes", headers=auth(users, "student")).status_code
        == 403
    )
    classroom, assignment, _ = setup_assignment(classroom_api)
    assert client.get("/teacher/classes", headers=auth(users, "other")).json() == []
    assert (
        client.get(
            f"/teacher/classes/{classroom['id']}/assignments",
            headers=auth(users, "other"),
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/teacher/assignments/{assignment['id']}", headers=auth(users, "other")
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/teacher/classes/{classroom['id']}/assignments",
            data={"title": "No"},
            files={"images": ("x.png", png(), "image/png")},
            headers=auth(users, "other"),
        ).status_code
        == 404
    )


def test_registration_cannot_claim_teacher_email(classroom_api, monkeypatch):
    client, _, _, _ = classroom_api
    monkeypatch.setenv("TEACHER_EMAILS", "reserved@example.com")
    response = client.post(
        "/auth/register",
        json={
            "email": "reserved@example.com",
            "password": "test-password-123",
            "role": "teacher",
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize("display_name,expected", [("  Sýnikennari  ", "Sýnikennari"), (None, None), ("   ", None)])
def test_class_home_exposes_owner_display_name_without_email_fallback(classroom_api, display_name, expected):
    client, session, users, _ = classroom_api
    users["teacher"].full_name = display_name
    session.add(users["teacher"])
    session.commit()
    response = client.post("/teacher/classes", json={"name": "Stærðfræði 8.B"}, headers=auth(users, "teacher"))
    assert response.status_code == 200
    classroom = response.json()
    assert classroom["teacher_name"] == expected
    joined = client.post("/student/classes/join", json={"join_code": classroom["join_code"]}, headers=auth(users, "student"))
    assert joined.status_code == 200
    assert joined.json()["teacher_name"] == expected
    listed = client.get("/student/classes", headers=auth(users, "student"))
    assert listed.json()[0]["teacher_name"] == expected
    assert users["teacher"].email not in listed.text
    assert client.get("/student/classes", headers=auth(users, "outsider")).json() == []


def test_query_without_gemini_has_clear_configuration_failure(
    classroom_api, monkeypatch
):
    client, _, users, _ = classroom_api
    monkeypatch.setenv("GEMINI_API_KEY", "")

    def unexpected_call(*args, **kwargs):
        raise AssertionError("An unconfigured query must never call an AI provider")

    monkeypatch.setattr(
        "backend.routes.query.call_legibility_with_retry", unexpected_call
    )
    problem = client.post(
        "/problem", json={"title": "Test"}, headers=auth(users, "student")
    ).json()
    response = client.post(
        "/query",
        data={"problem_id": problem["id"], "mode": "hint"},
        files=[
            ("prob_image", ("p.png", png(), "image/png")),
            ("sol_images", ("s.png", png(), "image/png")),
            ("drawing_data_pages", ("s.pk", b"drawing", "application/octet-stream")),
        ],
        headers=auth(users, "student"),
    )
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_student_join_listing_and_repeat_start(classroom_api):
    client, session, users, _ = classroom_api
    classroom, assignment, items = setup_assignment(classroom_api)
    joined = client.post(
        "/student/classes/join",
        json={"join_code": classroom["join_code"]},
        headers=auth(users, "student"),
    )
    assert joined.json()["student_count"] == 1
    assert (
        client.get("/student/classes", headers=auth(users, "student")).json()[0]["id"]
        == classroom["id"]
    )
    assert (
        client.get("/student/assignments", headers=auth(users, "outsider")).json() == []
    )
    assert start(classroom_api, assignment, items[0], "outsider").status_code == 404
    first = start(classroom_api, assignment, items[0])
    assert first.status_code == 200, first.text
    again = start(classroom_api, assignment, items[0])
    assert again.json()["problem"]["id"] == first.json()["problem"]["id"]
    assert first.json()["problem"]["user_id"] == str(users["student"].id)
    assert len(session.exec(select(Problem)).all()) == 1
    listing = client.get("/student/assignments", headers=auth(users, "student")).json()
    assert listing[0]["items"][0]["problem_id"] == first.json()["problem"]["id"]
    assert len(listing[0]["items"]) == 2
    assert client.get(first.json()["image_url"]).status_code == 200


@pytest.mark.parametrize(
    "files,expected",
    [
        ([("images", ("bad.png", b"not an image", "image/png"))], 422),
        (
            [
                ("images", ("ok.png", png(), "image/png")),
                ("images", ("bad.png", b"oops", "image/png")),
            ],
            422,
        ),
        ([("images", ("big.png", b"x" * (7 * 1024 * 1024 + 1), "image/png"))], 413),
        ([("images", ("x.png", png(), "image/png"))] * 13, 422),
    ],
)
def test_invalid_uploads_leave_no_assignment_or_artifacts(
    classroom_api, files, expected
):
    client, _, users, root = classroom_api
    response = client.post(
        "/teacher/classes", json={"name": "Algebra"}, headers=auth(users, "teacher")
    )
    assert response.status_code == 200, response.text
    url = f"/teacher/classes/{response.json()['id']}/assignments"
    response = client.post(
        url, data={"title": "Bad images"}, files=files, headers=auth(users, "teacher")
    )
    assert response.status_code == expected, response.text
    assert client.get(url, headers=auth(users, "teacher")).json() == []
    assert not list((root / "artifacts").rglob("*.*"))


def test_progress_and_errors_only_include_assignment_linked_attempts(classroom_api):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api)
    first = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    second = start(classroom_api, assignment, items[1]).json()["problem"]["id"]
    add_attempt(classroom_api, first, verdict="incorrect", error="sign_error")
    add_attempt(classroom_api, first, mode="hint", verdict="fully_solved", minute=1)
    add_attempt(classroom_api, second, mode="reveal", verdict="fully_solved")
    add_attempt(classroom_api, second, verdict="correct_so_far", minute=1)
    private = Problem(user_id=users["student"].id, title="Private notebook")
    session.add(private)
    session.commit()
    add_attempt(
        classroom_api, str(private.id), verdict="fully_solved", error="private_error"
    )
    url = f"/teacher/assignments/{assignment['id']}"
    detail = client.get(url, headers=auth(users, "teacher")).json()
    row = detail["students"][0]
    assert row["completed_count"] == 0
    assert row["attempt_count"] == 4
    assert row["hint_count"] == 1
    assert row["needs_attention"] is True
    assert detail["common_errors"] == [{"error_type": "sign_error", "count": 1}]
    add_attempt(classroom_api, first, verdict="fully_solved", minute=2)
    detail = client.get(url, headers=auth(users, "teacher")).json()
    assert detail["students"][0]["completed_count"] == 1
    assert detail["students"][0]["needs_attention"] is False
    inspection = client.get(
        f"{url}/students/{users['student'].id}", headers=auth(users, "teacher")
    ).json()
    assert sum(len(item["attempts"]) for item in inspection["items"]) == 5
    assert {item["problem_id"] for item in inspection["items"]} == {first, second}
    assert (
        client.get(
            f"{url}/students/{users['outsider'].id}", headers=auth(users, "teacher")
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{url}/students/{users['student'].id}", headers=auth(users, "other")
        ).status_code
        == 404
    )


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_transparent_exercise_images_keep_dark_ink_on_white(classroom_api, mode):
    client, _, users, _ = classroom_api
    if mode == "RGBA":
        source = Image.new(mode, (32, 32), (0, 0, 0, 0))
        ink = (0, 0, 0, 255)
    elif mode == "LA":
        source = Image.new(mode, (32, 32), (0, 0))
        ink = (0, 255)
    else:
        source = Image.new(mode, (32, 32), 0)
        source.putpalette([0, 0, 0] * 256)
        source.info["transparency"] = 0
        ink = 1
    source.paste(ink, (8, 8, 24, 24))
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    classroom = client.post(
        "/teacher/classes", json={"name": "Math"}, headers=auth(users, "teacher")
    ).json()
    response = client.post(
        f"/teacher/classes/{classroom['id']}/assignments",
        data={"title": "Transparent handwriting"},
        files={"images": ("handwriting.png", buffer.getvalue(), "image/png")},
        headers=auth(users, "teacher"),
    )
    assert response.status_code == 200, response.text
    assignment = response.json()
    detail = client.get(
        f"/teacher/assignments/{assignment['id']}", headers=auth(users, "teacher")
    ).json()
    image_bytes = client.get(detail["items"][0]["image_url"]).content
    with Image.open(BytesIO(image_bytes)) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.size == (32, 32)
        assert min(normalized.getpixel((0, 0))) >= 245
        assert max(normalized.getpixel((16, 16))) <= 10


def test_delete_assignment_notebook_preserves_restart_and_move_is_safe(classroom_api):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem = start(classroom_api, assignment, items[0]).json()["problem"]
    add_attempt(classroom_api, problem["id"], verdict="fully_solved")
    folder = client.post(
        "/folders", json={"name": "Moved"}, headers=auth(users, "student")
    ).json()
    moved = client.patch(
        f"/problems/{problem['id']}/move",
        json={"folder_id": folder["id"]},
        headers=auth(users, "student"),
    )
    assert moved.status_code == 200, moved.text
    assert (
        start(classroom_api, assignment, items[0]).json()["problem"]["id"]
        == problem["id"]
    )
    deleted = client.delete(
        f"/problems/{problem['id']}", headers=auth(users, "student")
    )
    assert deleted.status_code == 200, deleted.text
    detail = client.get(
        f"/teacher/assignments/{assignment['id']}", headers=auth(users, "teacher")
    ).json()
    assert detail["students"][0]["completed_count"] == 0
    assert detail["students"][0]["attempt_count"] == 0
    restarted = start(classroom_api, assignment, items[0])
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["problem"]["id"] != problem["id"]


def test_handwriting_links_are_signed_and_private(classroom_api):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    from backend.storage.r2 import upload_bytes

    key = f"attempts/{users['student'].id}/page.png"
    upload_bytes(key=key, data=png(), content_type="image/png")
    attempt = add_attempt(classroom_api, problem_id)
    attempt.solution_image_key = key
    attempt.solution_page_keys = [key]
    session.add(attempt)
    session.commit()
    url = f"/teacher/assignments/{assignment['id']}/students/{users['student'].id}"
    inspection = client.get(url, headers=auth(users, "teacher")).json()
    result = inspection["items"][0]["attempts"][0]
    assert result["message_is"] == "Skoðaðu annað skrefið."
    assert len(result["solution_page_urls"]) == 1
    asset_url = result["solution_image_url"]
    assert asset_url.startswith("http://testserver/")
    assert client.get(asset_url).content == png()
    assert client.get(asset_url.split("?")[0]).status_code in {403, 422}


def test_long_assignment_titles_fit_postgres_item_column(classroom_api):
    client, _, users, _ = classroom_api
    response = client.post(
        "/teacher/classes", json={"name": "Math"}, headers=auth(users, "teacher")
    )
    response = client.post(
        f"/teacher/classes/{response.json()['id']}/assignments",
        data={"title": "A" * 255},
        files={"images": ("a.png", png(), "image/png")},
        headers=auth(users, "teacher"),
    )
    assert response.status_code == 200, response.text
    detail = client.get(
        f"/teacher/assignments/{response.json()['id']}", headers=auth(users, "teacher")
    ).json()
    assert len(detail["items"][0]["title"]) <= 255


def test_unclear_hint_needs_attention_until_readable_check(classroom_api):
    client, _, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    add_attempt(classroom_api, problem_id, mode="hint", verdict="unclear")
    url = f"/teacher/assignments/{assignment['id']}"
    assert (
        client.get(url, headers=auth(users, "teacher")).json()["students"][0][
            "needs_attention"
        ]
        is True
    )
    add_attempt(classroom_api, problem_id, verdict="correct_so_far", minute=1)
    assert (
        client.get(url, headers=auth(users, "teacher")).json()["students"][0][
            "needs_attention"
        ]
        is False
    )


def test_storage_failure_cleans_even_the_last_partially_written_image(
    classroom_api, monkeypatch
):
    client, _, users, root = classroom_api
    classroom = client.post(
        "/teacher/classes", json={"name": "Math"}, headers=auth(users, "teacher")
    ).json()
    from backend.storage.r2 import upload_bytes

    count = 0

    def interrupted_upload(**kwargs):
        nonlocal count
        count += 1
        result = upload_bytes(**kwargs)
        if count == 2:
            raise OSError("Connection lost after object write")
        return result

    monkeypatch.setattr("backend.routes.classroom.upload_bytes", interrupted_upload)
    url = f"/teacher/classes/{classroom['id']}/assignments"
    response = client.post(
        url,
        data={"title": "Interrupted"},
        files=[("images", ("a.png", png(), "image/png"))] * 2,
        headers=auth(users, "teacher"),
    )
    assert response.status_code == 502
    assert client.get(url, headers=auth(users, "teacher")).json() == []
    assert not list((root / "artifacts").rglob("*.jpg"))


def test_stale_cross_owner_notebook_link_never_exposes_attempts(classroom_api):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    start(classroom_api, assignment, items[0])
    private = Problem(user_id=users["outsider"].id, title="Private outsider work")
    session.add(private)
    session.commit()
    add_attempt(
        classroom_api,
        str(private.id),
        user_name="outsider",
        verdict="fully_solved",
        error="private_error",
    )
    from backend.models.classroom_models import StudentAssignmentItem

    link = session.exec(select(StudentAssignmentItem)).one()
    link.problem_id = private.id
    session.add(link)
    session.commit()
    url = f"/teacher/assignments/{assignment['id']}"
    detail = client.get(url, headers=auth(users, "teacher")).json()
    assert detail["students"][0]["attempt_count"] == 0
    assert detail["common_errors"] == []
    inspection = client.get(
        f"{url}/students/{users['student'].id}", headers=auth(users, "teacher")
    ).json()
    assert inspection["items"][0]["problem_id"] is None
    assert inspection["items"][0]["attempts"] == []
    restarted = start(classroom_api, assignment, items[0]).json()["problem"]
    assert restarted["id"] != str(private.id)
    assert restarted["user_id"] == str(users["student"].id)


def test_invalid_total_bytes_and_pixels_leave_no_artifacts(classroom_api, monkeypatch):
    client, _, users, root = classroom_api
    classroom = client.post(
        "/teacher/classes", json={"name": "Math"}, headers=auth(users, "teacher")
    ).json()
    url = f"/teacher/classes/{classroom['id']}/assignments"
    monkeypatch.setattr("backend.routes.classroom.MAX_TOTAL_BYTES", len(png()) + 1)
    response = client.post(
        url,
        data={"title": "Too many bytes"},
        files=[("images", ("a.png", png(), "image/png"))] * 2,
        headers=auth(users, "teacher"),
    )
    assert response.status_code == 413
    monkeypatch.setattr("backend.routes.classroom.MAX_IMAGE_PIXELS", 400)
    response = client.post(
        url,
        data={"title": "Too many pixels"},
        files={"images": ("a.png", png(), "image/png")},
        headers=auth(users, "teacher"),
    )
    assert response.status_code == 413
    assert client.get(url, headers=auth(users, "teacher")).json() == []
    assert not list((root / "artifacts").rglob("*.jpg"))


def test_existing_query_flow_persists_assignment_progress_and_handwriting(
    classroom_api, monkeypatch
):
    client, _, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-never-sent")

    def synthetic_feedback(**kwargs):
        return {
            "response_text": json.dumps(
                {
                    "verdict": "fully_solved",
                    "response_type": "feedback",
                    "message_is": "Prófgögn: rétt lausn.",
                }
            ),
            "model_name": "synthetic-test-only",
        }

    monkeypatch.setattr(
        "backend.routes.query.call_mode_v3_with_retry", synthetic_feedback
    )
    response = client.post(
        "/query",
        data={
            "problem_id": problem_id,
            "mode": "check_solution",
            "pipeline_mode": "single_pass",
        },
        files=[
            ("prob_image", ("p.png", png(), "image/png")),
            ("sol_images", ("s.png", png(), "image/png")),
            (
                "drawing_data_pages",
                ("s.pk", b"synthetic-drawing", "application/octet-stream"),
            ),
        ],
        headers=auth(users, "student"),
    )
    assert response.status_code == 200, response.text
    detail_url = f"/teacher/assignments/{assignment['id']}"
    detail = client.get(detail_url, headers=auth(users, "teacher")).json()
    assert detail["students"][0]["completed_count"] == 1
    inspection = client.get(
        f"{detail_url}/students/{users['student'].id}", headers=auth(users, "teacher")
    ).json()
    attempt = inspection["items"][0]["attempts"][0]
    assert attempt["message_is"] == "Prófgögn: rétt lausn."
    assert len(attempt["solution_page_urls"]) == 1
    assert client.get(attempt["solution_page_urls"][0]).content == png()


def test_ordinary_problem_list_identifies_assigned_notebooks(classroom_api):
    client, _, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    response = start(classroom_api, assignment, items[0]).json()
    for problem in [
        response["problem"],
        client.get("/problems", headers=auth(users, "student")).json()[0],
    ]:
        assert problem.get("assignment_id") == assignment["id"]
        assert problem.get("assignment_item_id") == items[0]["id"]
        assert problem["created_at"].endswith("Z")
        assert problem["updated_at"].endswith("Z")
        assert client.get(problem["assignment_image_url"]).status_code == 200
    personal = client.post(
        "/problem", json={"title": "Private"}, headers=auth(users, "student")
    ).json()
    assert personal.get("assignment_id") is None
    assert personal.get("assignment_item_id") is None


def test_query_always_uses_teacher_image_for_assigned_notebook(
    classroom_api, monkeypatch
):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem_id = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    canonical = client.get(items[0]["image_url"]).content
    buffer = BytesIO()
    Image.new("RGB", (12, 12), "black").save(buffer, format="PNG")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-only")
    seen_pixels = []

    def inspect_canonical(**kwargs):
        seen_pixels.append(kwargs["prob_image"].getpixel((0, 0)))
        return {
            "response_text": json.dumps(
                {
                    "verdict": "fully_solved",
                    "response_type": "feedback",
                    "message_is": "Synthetic test.",
                }
            )
        }

    monkeypatch.setattr(
        "backend.routes.query.call_mode_v3_with_retry", inspect_canonical
    )
    response = client.post(
        "/query",
        data={
            "problem_id": problem_id,
            "mode": "check_solution",
            "pipeline_mode": "single_pass",
        },
        files=[
            ("prob_image", ("replacement.png", buffer.getvalue(), "image/png")),
            ("sol_images", ("s.png", png(), "image/png")),
            (
                "drawing_data_pages",
                ("s.pk", b"synthetic-drawing", "application/octet-stream"),
            ),
        ],
        headers=auth(users, "student"),
    )
    assert response.status_code == 200, response.text
    assert seen_pixels == [(255, 255, 255)]
    attempt = session.exec(
        select(Attempt).where(Attempt.problem_id == UUID(problem_id))
    ).one()
    from backend.storage.r2 import presigned_get_url

    assert (
        client.get(presigned_get_url(key=attempt.problem_image_key)).content
        == canonical
    )


def test_concurrent_restart_returns_one_linked_notebook(classroom_api, monkeypatch):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    previous = start(classroom_api, assignment, items[0]).json()["problem"]["id"]
    deleted = client.delete(f"/problems/{previous}", headers=auth(users, "student"))
    assert deleted.status_code == 200, deleted.text

    from backend.models.classroom_models import StudentAssignmentItem
    from backend.routes import classroom

    assert session.exec(select(StudentAssignmentItem)).one().problem_id is None
    student_id = users["student"].id
    assignment_id = UUID(assignment["id"])
    item_id = UUID(items[0]["id"])
    engine = session.get_bind()
    both_read_empty_link = Barrier(2)
    ensure_folder = classroom._ensure_default_folder

    def synchronize_after_read(**kwargs):
        folder = ensure_folder(**kwargs)
        both_read_empty_link.wait(timeout=10)
        return folder

    monkeypatch.setattr(classroom, "_ensure_default_folder", synchronize_after_read)

    def restart(_):
        with Session(engine) as request_session:
            response = classroom.start_assignment_item(
                assignment_id=assignment_id,
                item_id=item_id,
                session=request_session,
                user=request_session.get(User, student_id),
            )
            return response.problem.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        returned_ids = list(executor.map(restart, range(2)))

    assert returned_ids[0] == returned_ids[1]
    session.expire_all()
    notebooks = session.exec(select(Problem).where(Problem.user_id == student_id)).all()
    assert [notebook.id for notebook in notebooks] == [returned_ids[0]]
    assert (
        session.exec(select(StudentAssignmentItem)).one().problem_id == returned_ids[0]
    )
    add_attempt(classroom_api, str(returned_ids[0]), verdict="fully_solved")
    detail = client.get(
        f"/teacher/assignments/{assignment_id}", headers=auth(users, "teacher")
    ).json()
    assert detail["students"][0]["completed_count"] == 1
