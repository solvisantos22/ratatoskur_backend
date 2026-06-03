# app/auth/jwt.py
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from jose import jwt, JWTError

from backend.config import JWT_SECRET, JWT_ALG, ACCESS_TOKEN_TTL_MIN


def utcnow():
    return datetime.now(timezone.utc)


def create_access_token(user_id: UUID) -> str:
    exp = utcnow() + timedelta(minutes=ACCESS_TOKEN_TTL_MIN)
    payload = {
        "sub": str(user_id),
        "exp": int(exp.timestamp()),
        "iat": int(utcnow().timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_access_token(token: str) -> Optional[UUID]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("type") != "access":
            return None
        sub = payload.get("sub")
        if not sub:
            return None
        return UUID(sub)
    except (JWTError, ValueError):
        return None
