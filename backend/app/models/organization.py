from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.core.timeutils import utcnow as _now
from app.models.enums import (
    AttendanceMode,
    CheckoutPolicy,
    CompanyType,
    ConfirmationPolicy,
    EmploymentStatus,
    Role,
    SubscriptionPlan,
)
from app.models.mixins import IdMixin, OrgScopedMixin, TimestampMixin, str_enum


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(str_enum(SubscriptionPlan), default=SubscriptionPlan.FREE, nullable=False)
    company_type: Mapped[CompanyType] = mapped_column(str_enum(CompanyType), default=CompanyType.OTHER, nullable=False)

    settings: Mapped[OrganizationSettings] = relationship(back_populates="organization", uselist=False, cascade="all, delete-orphan")


class OrganizationSettings(Base):
    """Per-tenant attendance & geofencing policy. Single source for tunables (nothing hardcoded elsewhere)."""

    __tablename__ = "organization_settings"
    __table_args__ = (
        CheckConstraint("default_radius_m BETWEEN 10 AND 5000", name="radius_range"),
        CheckConstraint("required_consecutive >= 1", name="consecutive_min"),
        CheckConstraint("half_day_ratio > 0 AND half_day_ratio <= 1", name="half_day_ratio_range"),
    )

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    organization: Mapped[Organization] = relationship(back_populates="settings")

    confirmation_policy: Mapped[ConfirmationPolicy] = mapped_column(str_enum(ConfirmationPolicy), default=ConfirmationPolicy.AUTOMATIC, nullable=False)
    checkout_policy: Mapped[CheckoutPolicy] = mapped_column(str_enum(CheckoutPolicy), default=CheckoutPolicy.AUTO_CLOSE, nullable=False)

    # Geofence defaults applied to new offices
    default_radius_m: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    default_max_accuracy_m: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    required_consecutive: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    stability_window_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    entry_buffer_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    exit_buffer_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # GPS validation
    max_reasonable_accuracy_m: Mapped[float] = mapped_column(Float, default=1000.0, nullable=False)
    max_speed_mps: Mapped[float] = mapped_column(Float, default=70.0, nullable=False)  # ~250 km/h
    max_event_age_hours: Mapped[int] = mapped_column(Integer, default=72, nullable=False)
    require_registered_device: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Privacy: tracking only around scheduled shifts
    pre_shift_tracking_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    post_shift_tracking_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    location_retention_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)

    # Hybrid attendance policy
    temporary_exit_max_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    count_temporary_exit_as_work: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lunch_detection_tolerance_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    half_day_ratio: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    missing_checkin_after_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    confirmation_reminder_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    location_fresh_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # Web/PWA mode: attendance comes from explicit check-in/out. When enabled, stable geofence
    # transitions from periodic presence checks also open/close sessions automatically.
    auto_geofence_attendance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkout_requires_geofence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkin_reminder_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    # Monitoring: a validated presence older than this is shown as STALE (privacy: no background tracking,
    # so freshness depends on the employee keeping the attendance screen open).
    presence_stale_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)

    # ---- Automatic attendance policy ----
    attendance_mode: Mapped[AttendanceMode] = mapped_column(str_enum(AttendanceMode), default=AttendanceMode.MANUAL, nullable=False)
    automatic_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automatic_checkin_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automatic_checkout_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automatic_resume_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    presence_interval_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    entry_confirmation_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    exit_confirmation_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    temporary_exit_grace_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    checkout_grace_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    automatic_checkout_timeout_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    allow_unscheduled_attendance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def automatic_attendance(self) -> bool:
        """Confirmed geofence transitions open/close sessions (AUTOMATIC/HYBRID, or the legacy flag)."""
        return (self.attendance_mode != AttendanceMode.MANUAL or self.auto_geofence_attendance) and self.automatic_detection_enabled

    @property
    def manual_actions_allowed(self) -> bool:
        return self.attendance_mode != AttendanceMode.AUTOMATIC


class Department(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)


class User(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[Role] = mapped_column(str_enum(Role), nullable=False, default=Role.EMPLOYEE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invite_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    employee: Mapped[Employee | None] = relationship(back_populates="user", uselist=False)
    managed_departments: Mapped[list[Department]] = relationship(secondary="manager_departments", lazy="selectin")


class ManagerDepartment(OrgScopedMixin, Base):
    __tablename__ = "manager_departments"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True)


class Employee(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("organization_id", "employee_code"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    primary_office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    employee_code: Mapped[str] = mapped_column(String(40), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str | None] = mapped_column(String(120), nullable=True)
    employment_status: Mapped[EmploymentStatus] = mapped_column(str_enum(EmploymentStatus), default=EmploymentStatus.ACTIVE, nullable=False)
    hired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="employee")
    department: Mapped[Department | None] = relationship(lazy="joined")
    primary_office = relationship("Office", foreign_keys=[primary_office_id], lazy="joined")


class RefreshToken(IdMixin, OrgScopedMixin, Base):
    """Server-side refresh token registry for rotation + reuse detection."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, nullable=False)
