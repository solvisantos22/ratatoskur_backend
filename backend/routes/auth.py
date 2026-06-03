# app/routes/auth.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlmodel import Session

from backend.config import (
    REFRESH_TOKEN_TTL_DAYS,
    REFRESH_COOKIE_NAME,
    COOKIE_SECURE,
    COOKIE_SAMESITE,
    COOKIE_PATH,
)
from backend.db import get_session
from backend.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    UpdateMeRequest,
    UpdateConsentRequest,
    TokenResponse,
    MeResponse,
)
from backend.repositories.auth_repo import (
    get_user_by_email,
    create_user,
    verify_password,
    create_refresh_token,
    validate_refresh_cookie,
    rotate_refresh_token,
    revoke_refresh_token,
)
from backend.auth.jwt import create_access_token
from backend.auth.deps import get_current_user
from backend.models.auth_models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(resp: Response, value: str) -> None:
    resp.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=value,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,  # "lax" | "strict" | "none"
        path=COOKIE_PATH,
        max_age=REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60,
    )


def _clear_refresh_cookie(resp: Response) -> None:
    resp.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=COOKIE_PATH,
    )


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, resp: Response, session: Session = Depends(get_session)):
    existing = get_user_by_email(session, payload.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = create_user(
        session,
        payload.email,
        payload.password,
        payload.full_name,
        consent_analytics=payload.consent_analytics,
        consent_dataset_internal=payload.consent_dataset_internal,
        consent_dataset_publish=payload.consent_dataset_publish,
    )

    # Create refresh token + set cookie
    _, cookie_value = create_refresh_token(
        session=session,
        user_id=user.id,
        ttl_days=REFRESH_TOKEN_TTL_DAYS,
    )
    _set_refresh_cookie(resp, cookie_value)

    # Return access token
    access = create_access_token(user.id)
    return TokenResponse(access_token=access)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, resp: Response, request: Request, session: Session = Depends(get_session)):
    user = get_user_by_email(session, payload.email)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Capture optional metadata
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    # Create refresh token + set cookie
    _, cookie_value = create_refresh_token(
        session=session,
        user_id=user.id,
        ttl_days=REFRESH_TOKEN_TTL_DAYS,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    _set_refresh_cookie(resp, cookie_value)

    # Return access token
    access = create_access_token(user.id)
    return TokenResponse(access_token=access)


@router.post("/refresh", response_model=TokenResponse)
def refresh(resp: Response, request: Request, session: Session = Depends(get_session)):
    cookie_value = request.cookies.get(REFRESH_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    validated = validate_refresh_cookie(session, cookie_value)
    if not validated:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user, old_rt = validated

    # Rotate refresh token (revoke old, issue new)
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    _, new_cookie_value = rotate_refresh_token(
        session=session,
        old_rt=old_rt,
        ttl_days=REFRESH_TOKEN_TTL_DAYS,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    _set_refresh_cookie(resp, new_cookie_value)

    access = create_access_token(user.id)
    return TokenResponse(access_token=access)


@router.post("/logout")
def logout(resp: Response, request: Request, session: Session = Depends(get_session)):
    cookie_value = request.cookies.get(REFRESH_COOKIE_NAME)
    if cookie_value:
        validated = validate_refresh_cookie(session, cookie_value)
        if validated:
            _, rt = validated
            revoke_refresh_token(session, rt)

    _clear_refresh_cookie(resp)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    return MeResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        anon_user_id=user.anon_user_id,
        consent_analytics=user.consent_analytics,
        consent_dataset_internal=user.consent_dataset_internal,
        consent_dataset_publish=user.consent_dataset_publish,
    )


@router.patch("/me", response_model=MeResponse)
def update_me(
    payload: UpdateMeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    full_name = payload.full_name
    if full_name is not None:
        full_name = full_name.strip() or None

    user.full_name = full_name
    session.add(user)
    session.commit()
    session.refresh(user)

    return MeResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        anon_user_id=user.anon_user_id,
        consent_analytics=user.consent_analytics,
        consent_dataset_internal=user.consent_dataset_internal,
        consent_dataset_publish=user.consent_dataset_publish,
    )


@router.patch("/consent", response_model=MeResponse)
def update_consent(
    payload: UpdateConsentRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    changed = False
    if payload.consent_analytics is not None:
        user.consent_analytics = payload.consent_analytics
        changed = True
    if payload.consent_dataset_internal is not None:
        user.consent_dataset_internal = payload.consent_dataset_internal
        changed = True
    if payload.consent_dataset_publish is not None:
        user.consent_dataset_publish = payload.consent_dataset_publish
        changed = True

    if changed:
        user.consent_updated_at = datetime.now(timezone.utc)
        session.add(user)
        session.commit()
        session.refresh(user)

    return MeResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        anon_user_id=user.anon_user_id,
        consent_analytics=user.consent_analytics,
        consent_dataset_internal=user.consent_dataset_internal,
        consent_dataset_publish=user.consent_dataset_publish,
    )
