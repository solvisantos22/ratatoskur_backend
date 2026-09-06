from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from backend.tests.test_classrooms import classroom_api


def test_app_imports_without_ai_credentials(tmp_path):
    env = dict(
        os.environ, GEMINI_API_KEY="", DATABASE_URL=f"sqlite:///{tmp_path / 'local.db'}"
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.main import app; from fastapi.testclient import TestClient; assert TestClient(app).get('/health').status_code == 200",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr


def test_local_storage_signed_expiry_and_key_binding(tmp_path, monkeypatch):
    from backend.main import app
    from backend.storage.r2 import upload_bytes, presigned_get_url

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_STORAGE_SIGNING_SECRET",
        "test-only-secret-which-is-at-least-32-characters",
    )
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    upload_bytes(key="safe/image.png", data=b"image", content_type="image/png")
    url = presigned_get_url(key="safe/image.png", expires_in_seconds=60)
    client = TestClient(app)
    assert client.get(url).content == b"image"
    assert (
        client.get(url.replace("safe/image.png", "safe/other.png")).status_code == 403
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query["expires"] = [str(int(query["expires"][0]) + 3600)]
    altered = urlunsplit(parts._replace(query=urlencode(query, doseq=True)))
    assert client.get(altered).status_code == 403
    import backend.storage.local as local

    monkeypatch.setattr(
        local.time, "time", lambda: int(parse_qs(parts.query)["expires"][0]) + 1
    )
    assert client.get(url).status_code == 403


@pytest.mark.parametrize(
    "key",
    [
        "../outside.png",
        "/etc/passwd",
        "safe/../../outside",
        "safe\\outside",
        "safe/./image.png",
    ],
)
def test_local_storage_rejects_traversal(tmp_path, monkeypatch, key):
    from backend.storage.r2 import upload_bytes

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        upload_bytes(key=key, data=b"bad", content_type="image/png")


def test_local_refresh_cookie_rotates_on_sqlite(classroom_api):
    client, _, _, _ = classroom_api
    register = client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "a-password-123"},
    )
    assert register.status_code == 200, register.text
    response = client.post("/auth/refresh")
    assert response.status_code == 200, response.text


def test_local_setup_creates_private_env_and_initializes_fresh_sqlite(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/setup_local.py"
    process = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    from dotenv import dotenv_values

    env_path = tmp_path / "backend/.env"
    config = dotenv_values(env_path)
    assert len(config["JWT_SECRET"]) >= 32
    assert len(config["LOCAL_STORAGE_SIGNING_SECRET"]) >= 32
    assert config["GEMINI_API_KEY"] == ""
    assert env_path.stat().st_mode & 0o077 == 0
    from sqlmodel import create_engine
    from sqlalchemy import inspect

    assert (
        "classrooms" in inspect(create_engine(config["DATABASE_URL"])).get_table_names()
    )
    old_env = env_path.read_text()
    repeated = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert env_path.read_text() == old_env


def test_local_setup_refuses_non_sqlite_database():
    from importlib.util import module_from_spec, spec_from_file_location

    script = Path(__file__).resolve().parents[2] / "scripts/setup_local.py"
    assert script.exists(), "Local setup script must exist"
    spec = spec_from_file_location("local_setup", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="SQLite"):
        module.initialize_local_database("postgresql://someone@example.invalid/db")


def test_classroom_migration_adds_and_removes_only_feature_tables(tmp_path):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from importlib.util import module_from_spec, spec_from_file_location
    from sqlalchemy import inspect
    from sqlmodel import SQLModel, create_engine
    from backend.models import classroom_models

    script = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/f2a7c8d9e1b3_add_teacher_classrooms.py"
    )
    assert script.exists(), "Classroom production migration must exist"
    spec = spec_from_file_location("classroom_migration", script)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    policy_migration = import_module("backend.alembic.versions.a6d4e2f1b9c0_add_assignment_solution_control")
    assert migration.down_revision == "e8b1d4c3f6a2"
    feature_tables = {
        "classrooms",
        "class_memberships",
        "assignments",
        "assignment_items",
        "student_assignment_items",
    }
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    original = [
        table
        for table in SQLModel.metadata.sorted_tables
        if table.name not in feature_tables
    ]
    SQLModel.metadata.create_all(engine, tables=original)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            policy_migration.upgrade()
            assert feature_tables <= set(inspect(connection).get_table_names())
            for name in feature_tables:
                expected = {
                    column.name for column in SQLModel.metadata.tables[name].columns
                }
                assert expected == {
                    column["name"] for column in inspect(connection).get_columns(name)
                }
            policy_migration.downgrade()
            migration.downgrade()
            assert not feature_tables & set(inspect(connection).get_table_names())
            assert "users" in inspect(connection).get_table_names()


def test_local_teacher_provisioning_preserves_existing_account(tmp_path):
    root = Path(__file__).resolve().parents[2]
    initialized = subprocess.run(
        [sys.executable, str(root / "scripts/setup_local.py"), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert initialized.returncode == 0, initialized.stderr
    script = root / "scripts/create_teacher.py"
    env_path = tmp_path / "backend/.env"
    args = [
        sys.executable,
        str(script),
        "--env-file",
        str(env_path),
        "--email",
        "local.teacher@example.com",
        "--name",
        "Local Teacher",
        "--password-env",
        "CLASSROOM_TEST_PASSWORD",
    ]
    env = dict(os.environ, CLASSROOM_TEST_PASSWORD="a-private-test-password")
    first = subprocess.run(args, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert "a-private-test-password" not in first.stdout
    from dotenv import dotenv_values
    from sqlmodel import Session, create_engine, select
    from backend.models.auth_models import User

    config = dotenv_values(env_path)
    assert config["TEACHER_EMAILS"] == "local.teacher@example.com"
    with Session(create_engine(config["DATABASE_URL"])) as session:
        users = session.exec(select(User)).all()
        assert len(users) == 1
        assert users[0].full_name == "Local Teacher"
        password_hash = users[0].password_hash
    second = subprocess.run(
        args,
        env=dict(env, CLASSROOM_TEST_PASSWORD="different-test-password"),
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    with Session(create_engine(config["DATABASE_URL"])) as session:
        assert session.exec(select(User)).one().password_hash == password_hash
