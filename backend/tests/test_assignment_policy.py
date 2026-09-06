from importlib import import_module
from io import StringIO
import json
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine, select

from backend.models.auth_models import Attempt
from backend.tests.test_classrooms import auth, classroom_api, png, setup_assignment, start


def set_policy(api, assignment, allowed, name="teacher"):
    client, _, users, _ = api
    return client.patch(
        f"/teacher/assignments/{assignment['id']}",
        headers=auth(users, name), json={"allow_reveal": allowed},
    )


def submit_mode(api, problem_id, mode):
    client, _, users, _ = api
    return client.post(
        "/query", headers=auth(users, "student"),
        data={"problem_id": problem_id, "mode": mode, "pipeline_mode": "single_pass"},
        files=[("prob_image", ("problem.png", png(), "image/png")),
               ("sol_images", ("solution.png", png(), "image/png")),
               ("drawing_data_pages", ("drawing.data", b"synthetic-ink", "application/octet-stream"))],
    )


def test_assignment_policy_creation_defaults_and_owner_only_updates(classroom_api):
    client, _, users, _ = classroom_api
    classroom, existing, _ = setup_assignment(classroom_api, count=1)
    assert existing["allow_reveal"] is True
    response = client.post(
        f"/teacher/classes/{classroom['id']}/assignments",
        headers=auth(users, "teacher"), data={"title": "Hints and checks", "allow_reveal": "false"},
        files=[("images", ("problem.png", png(), "image/png"))],
    )
    assert response.status_code == 200, response.text
    assignment = response.json()
    assert assignment["allow_reveal"] is False
    assert set_policy(classroom_api, assignment, True, "other").status_code == 404
    assert set_policy(classroom_api, assignment, True, "student").status_code == 403
    assert client.patch(f"/teacher/assignments/{assignment['id']}", json={"allow_reveal": True}).status_code == 401
    assert set_policy(classroom_api, assignment, "not-a-boolean").status_code == 422
    assert set_policy(classroom_api, assignment, True).json()["allow_reveal"] is True
    assert set_policy(classroom_api, assignment, False).json()["allow_reveal"] is False
    for url, name in [(f"/teacher/classes/{classroom['id']}/assignments", "teacher"),
                      ("/student/assignments", "student")]:
        listing = client.get(url, headers=auth(users, name)).json()
        assert next(row for row in listing if row["id"] == assignment["id"])["allow_reveal"] is False


def test_current_policy_is_returned_for_reopened_and_normal_list_notebooks(classroom_api):
    client, _, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    opened = start(classroom_api, assignment, items[0]).json()["problem"]
    assert opened["assignment_allow_reveal"] is True
    assert set_policy(classroom_api, assignment, False).status_code == 200
    reopened = start(classroom_api, assignment, items[0]).json()["problem"]
    assert reopened["id"] == opened["id"]
    assert reopened["assignment_allow_reveal"] is False
    problems = client.get("/problems", headers=auth(users, "student")).json()
    assert next(p for p in problems if p["id"] == opened["id"])["assignment_allow_reveal"] is False
    personal = client.post("/problem", headers=auth(users, "student"), json={"title": "Personal"}).json()
    assert personal.get("assignment_allow_reveal") is None


def test_disabling_full_solutions_blocks_existing_notebook_before_ai_or_writes(classroom_api, monkeypatch):
    client, session, users, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    problem = start(classroom_api, assignment, items[0]).json()["problem"]
    assert set_policy(classroom_api, assignment, False).status_code == 200
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-never-used")
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled reveal must not call AI or read/write artifacts")
    monkeypatch.setattr("backend.routes.query.call_mode_v3_with_retry", forbidden)
    monkeypatch.setattr("backend.routes.query.download_bytes", forbidden)
    monkeypatch.setattr("backend.routes.query.upload_bytes", forbidden)
    response = submit_mode(classroom_api, problem["id"], "reveal")
    assert response.status_code == 403, response.text
    assert "kennari" in response.json()["detail"].lower()
    assert not session.exec(select(Attempt).where(Attempt.problem_id == UUID(problem["id"]))).all()
    # Policy denial is meaningful even before the laptop's AI key is configured.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert submit_mode(classroom_api, problem["id"], "reveal").status_code == 403
    for mode in ("hint", "check_solution"):
        assert submit_mode(classroom_api, problem["id"], mode).status_code == 503
    # The teacher can enable it again; the same notebook reaches AI configuration.
    assert set_policy(classroom_api, assignment, True).status_code == 200
    assert submit_mode(classroom_api, problem["id"], "reveal").status_code == 503
    personal = client.post("/problem", headers=auth(users, "student"), json={"title": "Personal"}).json()
    assert submit_mode(classroom_api, personal["id"], "reveal").status_code == 503


def test_solution_control_migration_preserves_existing_assignments():
    migration = import_module("backend.alembic.versions.a6d4e2f1b9c0_add_assignment_solution_control")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE assignments (id TEXT PRIMARY KEY, title TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO assignments VALUES ('existing', 'Existing class work')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text("SELECT allow_reveal FROM assignments")).scalar_one() == 1
        connection.execute(text("UPDATE assignments SET allow_reveal = 0"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert [c["name"] for c in inspect(connection).get_columns("assignments")] == ["id", "title"]
        assert connection.execute(text("SELECT title FROM assignments")).scalar_one() == "Existing class work"
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert "BOOLEAN DEFAULT true NOT NULL" in output.getvalue()


@pytest.mark.parametrize("mode", ["hint", "check_solution"])
def test_restricted_assignments_still_receive_hints_and_checks(classroom_api, monkeypatch, mode):
    _, session, _, _ = classroom_api
    _, assignment, items = setup_assignment(classroom_api, count=1)
    assert set_policy(classroom_api, assignment, False).status_code == 200
    problem = start(classroom_api, assignment, items[0]).json()["problem"]
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-never-sent")
    calls = []
    def feedback(**kwargs):
        calls.append(kwargs)
        return {"response_text": json.dumps({"verdict": "correct_so_far", "response_type": "feedback", "message_is": "Prófgögn: næsta skref."}), "model_name": "synthetic-only"}
    monkeypatch.setattr("backend.routes.query.call_mode_v3_with_retry", feedback)
    response = submit_mode(classroom_api, problem["id"], mode)
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert session.exec(select(Attempt).where(Attempt.problem_id == UUID(problem["id"]))).one().mode == mode


def test_membership_change_does_not_remove_notebook_solution_restriction(classroom_api, monkeypatch):
    from backend.models.classroom_models import ClassMembership
    _, session, users, _ = classroom_api
    classroom, assignment, items = setup_assignment(classroom_api, count=1)
    problem = start(classroom_api, assignment, items[0]).json()["problem"]
    assert set_policy(classroom_api, assignment, False).status_code == 200
    session.delete(session.get(ClassMembership, (UUID(classroom["id"]), users["student"].id)))
    session.commit()
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert submit_mode(classroom_api, problem["id"], "reveal").status_code == 403


def test_local_setup_upgrades_only_known_assignment_column_and_is_idempotent(tmp_path):
    from scripts.setup_local import initialize_local_database
    url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        if "allow_reveal" in {c["name"] for c in inspect(connection).get_columns("assignments")}:
            connection.execute(text("ALTER TABLE assignments DROP COLUMN allow_reveal"))
        connection.execute(text("INSERT INTO assignments (id, class_id, title, created_at) VALUES ('old', 'class', 'Preserve me', CURRENT_TIMESTAMP)"))
    initialize_local_database(url)
    with engine.begin() as connection:
        assert "allow_reveal" in {c["name"] for c in inspect(connection).get_columns("assignments")}
        assert connection.execute(text("SELECT allow_reveal FROM assignments WHERE id = 'old'")).scalar_one() == 1
        connection.execute(text("UPDATE assignments SET allow_reveal = 0 WHERE id = 'old'"))
    initialize_local_database(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT title, allow_reveal FROM assignments WHERE id = 'old'")).one() == ("Preserve me", 0)
    engine.dispose()


def test_local_setup_rejects_other_missing_columns_without_applying_policy_upgrade(tmp_path):
    from scripts.setup_local import initialize_local_database
    url = f"sqlite:///{tmp_path / 'incomplete.db'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE assignments DROP COLUMN allow_reveal"))
        connection.execute(text("ALTER TABLE assignments DROP COLUMN title"))
    with pytest.raises(ValueError, match="different schema"):
        initialize_local_database(url)
    assert "allow_reveal" not in {c["name"] for c in inspect(engine).get_columns("assignments")}
    engine.dispose()
