# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    consent_analytics: bool = False
    consent_dataset_internal: bool = False
    consent_dataset_publish: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UpdateMeRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)


class UpdateConsentRequest(BaseModel):
    consent_analytics: bool | None = None
    consent_dataset_internal: bool | None = None
    consent_dataset_publish: bool | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    anon_user_id: str | None = None
    consent_analytics: bool | None = None
    consent_dataset_internal: bool | None = None
    consent_dataset_publish: bool | None = None
