import os

from fastapi import Depends, HTTPException

from backend.auth.deps import get_current_user
from backend.models.auth_models import User


def is_teacher_email(email: str) -> bool:
    allowed = {
        value.strip().lower()
        for value in os.getenv("TEACHER_EMAILS", "").split(",")
        if value.strip()
    }
    return email.strip().lower() in allowed


def get_teacher(user: User = Depends(get_current_user)) -> User:
    if not is_teacher_email(user.email):
        raise HTTPException(
            status_code=403,
            detail="This account does not have teacher access. Contact your administrator.",
        )
    return user
