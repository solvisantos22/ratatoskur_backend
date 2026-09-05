#!/usr/bin/env python3
"""Provision an account in the local SQLite database and add teacher access."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def provision(
    *, env_file: Path, email: str, name: str | None, password_env: str | None
) -> None:
    from dotenv import dotenv_values, set_key
    from sqlalchemy.engine import make_url
    from sqlmodel import Session, create_engine
    from backend.repositories.auth_repo import create_user, get_user_by_email
    from backend.schemas.auth import RegisterRequest

    config = dotenv_values(env_file)
    database_url = config.get("DATABASE_URL", "")
    if make_url(database_url).get_backend_name() != "sqlite":
        raise ValueError(
            "This helper only provisions local SQLite accounts. Production teacher access uses existing accounts."
        )
    email = email.strip().lower()
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            user = get_user_by_email(session, email)
            if user is None:
                password = (
                    os.getenv(password_env, "")
                    if password_env
                    else getpass.getpass(
                        "New teacher password (at least 8 characters): "
                    )
                )
                if password_env and not password:
                    raise ValueError(
                        f"Password environment variable {password_env} is empty"
                    )
                if not password_env and password != getpass.getpass(
                    "Repeat password: "
                ):
                    raise ValueError("Passwords do not match")
                payload = RegisterRequest(
                    email=email, password=password, full_name=name
                )
                create_user(session, payload.email, payload.password, payload.full_name)
            elif not user.is_active:
                raise ValueError(
                    "The existing account is inactive; access was not changed"
                )
    finally:
        engine.dispose()
    allowed = {
        value.strip().lower()
        for value in (config.get("TEACHER_EMAILS") or "").split(",")
        if value.strip()
    }
    allowed.add(email)
    set_key(str(env_file), "TEACHER_EMAILS", ",".join(sorted(allowed)))
    os.chmod(env_file, 0o600)
    print(
        f"Teacher access ready for {email}. Existing passwords are preserved. Restart the backend after changing its environment."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / "backend/.env")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name")
    parser.add_argument(
        "--password-env",
        help="Read a new account password from this environment variable instead of an interactive prompt",
    )
    args = parser.parse_args()
    try:
        provision(
            env_file=args.env_file,
            email=args.email,
            name=args.name,
            password_env=args.password_env,
        )
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
