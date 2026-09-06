#!/usr/bin/env python3
"""Initialize local SQLite and apply explicitly supported additive upgrades."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def initialize_local_database(database_url: str) -> None:
    from sqlalchemy import inspect
    from sqlalchemy.engine import make_url
    from sqlmodel import SQLModel, create_engine
    from backend.models import auth_models, classroom_models  # noqa: F401

    url = make_url(database_url)
    if (
        url.get_backend_name() != "sqlite"
        or not url.database
        or url.database == ":memory:"
    ):
        raise ValueError(
            "Local setup requires a file-backed SQLite database. Use Alembic for production."
        )
    Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url)
    try:
        existing = set(inspect(engine).get_table_names())
        if not existing:
            SQLModel.metadata.create_all(engine)
        elif not set(SQLModel.metadata.tables) <= existing:
            raise ValueError(
                "Existing database has a different schema. Use migrations or choose a new local database path."
            )
        else:
            # Validate first; never silently patch an unrelated/partial schema.
            missing_columns = {}
            for name, table in SQLModel.metadata.tables.items():
                columns = {column["name"] for column in inspect(engine).get_columns(name)}
                missing = set(table.columns.keys()) - columns
                if missing:
                    missing_columns[name] = missing
            if missing_columns and missing_columns != {"assignments": {"allow_reveal"}}:
                raise ValueError("Existing database has a different schema. Use migrations or choose a new local database path.")
            if missing_columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE assignments ADD COLUMN allow_reveal BOOLEAN NOT NULL DEFAULT 1")
    finally:
        engine.dispose()


def setup(root: Path) -> None:
    from dotenv import dotenv_values

    root = root.resolve()
    env_path = root / "backend/.env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        contents = (
            "# Generated local development settings. Never commit this file.\n"
            f"DATABASE_URL='sqlite:///{root / '.local/classroom.db'}'\n"
            f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
            "STORAGE_BACKEND=local\n"
            f"LOCAL_STORAGE_DIR='{root / '.local/artifacts'}'\n"
            f"LOCAL_STORAGE_SIGNING_SECRET={secrets.token_urlsafe(48)}\n"
            "PUBLIC_BASE_URL=http://127.0.0.1:8000\n"
            "TEACHER_EMAILS=\nGEMINI_API_KEY=\nCOOKIE_SECURE=false\nCOOKIE_SAMESITE=lax\n"
        )
        descriptor = os.open(env_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(contents)
        print(f"Created private local settings: {env_path}")
    config = dotenv_values(env_path)
    database_url = config.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing from backend/.env")
    initialize_local_database(database_url)
    print("Local SQLite database ready. Class management works without an AI key.")
    print(
        "Provision a teacher with .venv/bin/python scripts/create_teacher.py --email your-email --name Your-Name"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Local output directory (defaults to the repository)",
    )
    args = parser.parse_args()
    try:
        setup(args.root)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
