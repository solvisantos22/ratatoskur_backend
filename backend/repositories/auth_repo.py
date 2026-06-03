# app/repositories/auth_repo.py
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from passlib.context import CryptContext
from sqlmodel import Session, select

from backend.models.auth_models import User, RefreshToken

# Avoid bcrypt backend issues (and the 72-byte input limit) by using PBKDF2-SHA256.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------
# Password helpers
# -------------------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


# -------------------------
# Refresh token helpers
# -------------------------
def _new_selector() -> str:
    # URL-safe, short-ish; stored in DB + cookie, safe to reveal
    return secrets.token_urlsafe(32)

def _new_validator() -> str:
    # Secret; only goes to cookie; store only hash
    return secrets.token_urlsafe(32)

def _hash_validator(validator: str) -> str:
    return pwd_context.hash(validator)

def _verify_validator(validator: str, validator_hash: str) -> bool:
    return pwd_context.verify(validator, validator_hash)

def make_refresh_cookie_value(selector: str, validator: str) -> str:
    return f"{selector}.{validator}"

def parse_refresh_cookie_value(value: str) -> tuple[str, str] | None:
    if not value or "." not in value:
        return None
    selector, validator = value.split(".", 1)
    if not selector or not validator:
        return None
    return selector, validator


# -------------------------
# User queries
# -------------------------
def get_user_by_email(session: Session, email: str) -> Optional[User]:
    stmt = select(User).where(User.email == email.lower().strip())
    return session.exec(stmt).first()

def get_user(session: Session, user_id: UUID) -> Optional[User]:
    return session.get(User, user_id)

def create_user(
    session: Session,
    email: str,
    password: str,
    full_name: str | None = None,
    consent_analytics: bool = False,
    consent_dataset_internal: bool = False,
    consent_dataset_publish: bool = False,
) -> User:
    normalized_name = full_name.strip() if full_name is not None else None
    if normalized_name == "":
        normalized_name = None
    user = User(
        email=email.lower().strip(),
        password_hash=hash_password(password),
        full_name=normalized_name,
        consent_analytics=consent_analytics,
        consent_dataset_internal=consent_dataset_internal,
        consent_dataset_publish=consent_dataset_publish,
        consent_updated_at=utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# -------------------------
# Refresh token lifecycle
# -------------------------
def create_refresh_token(
    session: Session,
    user_id: UUID,
    ttl_days: int = 30,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[RefreshToken, str]:
    """
    Creates a refresh token row + returns (row, cookie_value).
    cookie_value is what you set as the HttpOnly cookie.
    """
    selector = _new_selector()
    validator = _new_validator()

    rt = RefreshToken(
        user_id=user_id,
        selector=selector,
        validator_hash=_hash_validator(validator),
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(days=ttl_days),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    session.add(rt)
    session.commit()
    session.refresh(rt)

    cookie_value = make_refresh_cookie_value(selector, validator)
    return rt, cookie_value


def get_refresh_token_by_selector(session: Session, selector: str) -> Optional[RefreshToken]:
    stmt = select(RefreshToken).where(RefreshToken.selector == selector)
    return session.exec(stmt).first()


def is_refresh_token_valid(rt: RefreshToken) -> bool:
    now = utcnow()
    if rt.revoked_at is not None:
        return False
    if rt.expires_at <= now:
        return False
    return True


def validate_refresh_cookie(
    session: Session,
    cookie_value: str,
) -> Optional[tuple[User, RefreshToken]]:
    """
    Validates cookie selector+validator, returns (user, refresh_token_row) if valid.
    """
    parsed = parse_refresh_cookie_value(cookie_value)
    if not parsed:
        return None
    selector, validator = parsed

    rt = get_refresh_token_by_selector(session, selector)
    if not rt or not is_refresh_token_valid(rt):
        return None

    if not _verify_validator(validator, rt.validator_hash):
        return None

    user = session.get(User, rt.user_id)
    if not user or not user.is_active:
        return None

    return user, rt


def revoke_refresh_token(session: Session, rt: RefreshToken) -> None:
    if rt.revoked_at is None:
        rt.revoked_at = utcnow()
        session.add(rt)
        session.commit()


def revoke_all_refresh_tokens_for_user(session: Session, user_id: UUID) -> None:
    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    )
    tokens = session.exec(stmt).all()
    now = utcnow()
    for t in tokens:
        t.revoked_at = now
        session.add(t)
    session.commit()


def rotate_refresh_token(
    session: Session,
    old_rt: RefreshToken,
    ttl_days: int = 30,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[RefreshToken, str]:
    """
    Rotation best practice: revoke old token and issue a new one.
    """
    revoke_refresh_token(session, old_rt)
    return create_refresh_token(
        session=session,
        user_id=old_rt.user_id,
        ttl_days=ttl_days,
        user_agent=user_agent,
        ip_address=ip_address,
    )
