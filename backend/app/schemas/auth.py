from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.timeutils import is_valid_timezone
from app.models.enums import CompanyType, Role
from app.schemas.common import ORMModel


class RegisterCompanyIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    timezone: str = "UTC"
    company_type: CompanyType = CompanyType.OTHER
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if not is_valid_timezone(v):
            raise ValueError("Unknown IANA timezone")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class LogoutIn(BaseModel):
    refresh_token: str | None = None


class GoogleAuthIn(BaseModel):
    id_token: str = Field(min_length=20)
    nonce: str | None = Field(default=None, max_length=128)
    # Only needed when registering a new workspace with Google
    company_name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str = "UTC"
    company_type: CompanyType = CompanyType.OTHER
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if not is_valid_timezone(v):
            raise ValueError("Unknown IANA timezone")
        return v


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=20)
    password: str = Field(min_length=10, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: Role
    organization_id: int
    organization_name: str
    organization_timezone: str
    subscription_plan: str
    has_password: bool
    google_linked: bool
    employee_id: int | None
    managed_department_ids: list[int]
    last_login_at: datetime | None
