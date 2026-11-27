from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.timeutils import is_valid_timezone
from app.models.enums import (
    AttendanceMode,
    CheckoutPolicy,
    CompanyType,
    ConfirmationPolicy,
    EmploymentStatus,
    Role,
    SubscriptionPlan,
)
from app.schemas.common import ORMModel


class OrganizationOut(ORMModel):
    id: int
    name: str
    slug: str
    timezone: str
    subscription_plan: SubscriptionPlan
    company_type: CompanyType
    is_active: bool
    created_at: datetime


class OrganizationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str | None = None
    company_type: CompanyType | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_timezone(v):
            raise ValueError("Unknown IANA timezone")
        return v


class SettingsOut(ORMModel):
    confirmation_policy: ConfirmationPolicy
    checkout_policy: CheckoutPolicy
    default_radius_m: float
    default_max_accuracy_m: float
    required_consecutive: int
    stability_window_seconds: int
    entry_buffer_m: float
    exit_buffer_m: float
    max_reasonable_accuracy_m: float
    max_speed_mps: float
    max_event_age_hours: int
    require_registered_device: bool
    pre_shift_tracking_minutes: int
    post_shift_tracking_minutes: int
    location_retention_days: int
    temporary_exit_max_minutes: int
    count_temporary_exit_as_work: bool
    lunch_detection_tolerance_minutes: int
    half_day_ratio: float
    missing_checkin_after_minutes: int
    confirmation_reminder_minutes: int
    location_fresh_minutes: int
    auto_geofence_attendance: bool
    checkout_requires_geofence: bool
    checkin_reminder_minutes: int
    presence_stale_seconds: int
    attendance_mode: AttendanceMode
    automatic_detection_enabled: bool
    automatic_checkin_enabled: bool
    automatic_checkout_enabled: bool
    automatic_resume_enabled: bool
    presence_interval_seconds: int
    entry_confirmation_count: int
    exit_confirmation_count: int
    temporary_exit_grace_minutes: int
    checkout_grace_minutes: int
    automatic_checkout_timeout_minutes: int
    allow_unscheduled_attendance: bool


class SettingsPatch(BaseModel):
    confirmation_policy: ConfirmationPolicy | None = None
    checkout_policy: CheckoutPolicy | None = None
    default_radius_m: float | None = Field(default=None, ge=10, le=5000)
    default_max_accuracy_m: float | None = Field(default=None, gt=0, le=1000)
    required_consecutive: int | None = Field(default=None, ge=1, le=20)
    stability_window_seconds: int | None = Field(default=None, ge=0, le=3600)
    entry_buffer_m: float | None = Field(default=None, ge=0, le=500)
    exit_buffer_m: float | None = Field(default=None, ge=0, le=500)
    max_reasonable_accuracy_m: float | None = Field(default=None, gt=0, le=10000)
    max_speed_mps: float | None = Field(default=None, gt=1, le=400)
    max_event_age_hours: int | None = Field(default=None, ge=1, le=720)
    require_registered_device: bool | None = None
    pre_shift_tracking_minutes: int | None = Field(default=None, ge=0, le=360)
    post_shift_tracking_minutes: int | None = Field(default=None, ge=0, le=720)
    location_retention_days: int | None = Field(default=None, ge=1, le=3650)
    temporary_exit_max_minutes: int | None = Field(default=None, ge=1, le=480)
    count_temporary_exit_as_work: bool | None = None
    lunch_detection_tolerance_minutes: int | None = Field(default=None, ge=0, le=120)
    half_day_ratio: float | None = Field(default=None, gt=0, le=1)
    missing_checkin_after_minutes: int | None = Field(default=None, ge=0, le=480)
    confirmation_reminder_minutes: int | None = Field(default=None, ge=1, le=1440)
    location_fresh_minutes: int | None = Field(default=None, ge=1, le=1440)
    auto_geofence_attendance: bool | None = None
    checkout_requires_geofence: bool | None = None
    checkin_reminder_minutes: int | None = Field(default=None, ge=0, le=240)
    presence_stale_seconds: int | None = Field(default=None, ge=30, le=3600)
    attendance_mode: AttendanceMode | None = None
    automatic_detection_enabled: bool | None = None
    automatic_checkin_enabled: bool | None = None
    automatic_checkout_enabled: bool | None = None
    automatic_resume_enabled: bool | None = None
    presence_interval_seconds: int | None = Field(default=None, ge=15, le=600)
    entry_confirmation_count: int | None = Field(default=None, ge=1, le=10)
    exit_confirmation_count: int | None = Field(default=None, ge=1, le=10)
    temporary_exit_grace_minutes: int | None = Field(default=None, ge=0, le=120)
    checkout_grace_minutes: int | None = Field(default=None, ge=0, le=240)
    automatic_checkout_timeout_minutes: int | None = Field(default=None, ge=5, le=720)
    allow_unscheduled_attendance: bool | None = None


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DepartmentOut(ORMModel):
    id: int
    name: str
    employee_count: int = 0


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    employee_code: str = Field(min_length=1, max_length=40)
    position: str | None = Field(default=None, max_length=120)
    department_id: int | None = None
    primary_office_id: int | None = None
    office_ids: list[int] = []
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    hired_at: date | None = None
    role: Role = Role.EMPLOYEE
    managed_department_ids: list[int] = []

    @model_validator(mode="after")
    def _owner(self):
        if self.role == Role.OWNER:
            raise ValueError("OWNER role cannot be assigned")
        return self


class EmployeePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    position: str | None = None
    department_id: int | None = None
    primary_office_id: int | None = None
    is_active: bool | None = None
    employment_status: EmploymentStatus | None = None
    hired_at: date | None = None
    role: Role | None = None
    managed_department_ids: list[int] | None = None
    office_ids: list[int] | None = None


class EmployeeOut(ORMModel):
    id: int
    user_id: int
    full_name: str
    email: str
    employee_code: str
    position: str | None
    employment_status: EmploymentStatus
    hired_at: date | None
    department_id: int | None
    department_name: str | None
    primary_office_id: int | None
    office_ids: list[int]
    role: Role
    managed_department_ids: list[int]
    is_active: bool
    invite_pending: bool
    consent_granted: bool | None
    location_permission: str | None
    created_at: datetime


class EmployeeCreated(EmployeeOut):
    invite_url: str | None = None
