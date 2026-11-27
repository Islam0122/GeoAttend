from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Float,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.core.timeutils import utcnow
from app.models.enums import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    AttendanceStatus,
    BreakType,
    CloseReason,
    CorrectionType,
    RequestStatus,
    SessionConfirmation,
    SessionSource,
    SessionStatus,
)
from app.models.mixins import IdMixin, OrgScopedMixin, TimestampMixin, str_enum


class AttendanceRecord(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    """One row per employee per work date (shift start date, employee-local)."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date"),
        Index("ix_attendance_records_org_date", "organization_id", "work_date"),
        CheckConstraint("late_minutes >= 0 AND early_departure_minutes >= 0 AND worked_minutes >= 0 AND break_minutes >= 0 AND overtime_minutes >= 0", name="non_negative"),
    )

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("work_schedules.id", ondelete="SET NULL"), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    scheduled_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scheduled_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grace_period_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_check_in: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    actual_check_out: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    early_departure_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(str_enum(AttendanceStatus), nullable=False, default=AttendanceStatus.ABSENT, index=True)
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_unscheduled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    early_arrival_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    presence_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)          # physically inside
    temporary_exit_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)    # away during sessions
    signal_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    missing_checkin_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sessions: Mapped[list[AttendanceSession]] = relationship(back_populates="record", lazy="selectin", order_by="AttendanceSession.check_in_at", cascade="all, delete-orphan")


class AttendanceSession(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        # At most one live (OPEN/AWAY) session per employee -> DB-level race protection.
        Index(
            "uq_attendance_sessions_one_live",
            "employee_id",
            unique=True,
            sqlite_where=text("status IN ('OPEN','AWAY')"),
            postgresql_where=text("status IN ('OPEN','AWAY')"),
        ),
        Index("ix_attendance_sessions_emp_checkin", "employee_id", "check_in_at"),
        CheckConstraint("check_out_at IS NULL OR check_out_at >= check_in_at", name="time_order"),
    )

    record_id: Mapped[int] = mapped_column(ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(str_enum(SessionStatus), nullable=False, default=SessionStatus.OPEN)
    confirmation: Mapped[SessionConfirmation] = mapped_column(str_enum(SessionConfirmation), nullable=False)
    source: Mapped[SessionSource] = mapped_column(str_enum(SessionSource), nullable=False, default=SessionSource.GPS)
    check_in_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    checkout_detected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    checkout_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    close_reason: Mapped[CloseReason | None] = mapped_column(str_enum(CloseReason), nullable=True)
    enter_transition_id: Mapped[int | None] = mapped_column(ForeignKey("geofence_transitions.id", ondelete="SET NULL"), nullable=True)
    exit_transition_id: Mapped[int | None] = mapped_column(ForeignKey("geofence_transitions.id", ondelete="SET NULL"), nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    check_in_event_id: Mapped[int | None] = mapped_column(ForeignKey("location_events.id", ondelete="SET NULL"), nullable=True)
    check_out_event_id: Mapped[int | None] = mapped_column(ForeignKey("location_events.id", ondelete="SET NULL"), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # payable: net of unpaid breaks, set when closed
    gross_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)     # check-in to check-out
    detection_method: Mapped[str] = mapped_column(String(16), default="MANUAL", nullable=False)
    check_in_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    record: Mapped[AttendanceRecord] = relationship(back_populates="sessions")
    breaks: Mapped[list[AttendanceBreak]] = relationship(back_populates="session", lazy="selectin", order_by="AttendanceBreak.started_at", cascade="all, delete-orphan")


class AttendanceBreak(IdMixin, OrgScopedMixin, Base):
    __tablename__ = "attendance_breaks"
    __table_args__ = (CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="time_order"),)

    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[BreakType] = mapped_column(str_enum(BreakType), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # If the employee has not re-entered by this instant the break is resolved
    # (temporary exit/lunch -> session closed at break start; business trip -> closed at expiry).
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    detection_method: Mapped[str] = mapped_column(String(16), default="AUTOMATIC", nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), default="OPEN", nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    session: Mapped[AttendanceSession] = relationship(back_populates="breaks")


class AttendanceCorrection(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "attendance_corrections"

    record_id: Mapped[int] = mapped_column(ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[CorrectionType] = mapped_column(str_enum(CorrectionType), nullable=False)
    requested_check_in: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    requested_check_out: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RequestStatus] = mapped_column(str_enum(RequestStatus), default=RequestStatus.PENDING, nullable=False, index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttendanceAnomaly(IdMixin, OrgScopedMixin, Base):
    """Signals for HR review. Never applied as an automatic penalty."""

    __tablename__ = "attendance_anomalies"
    __table_args__ = (Index("ix_attendance_anomalies_org_status", "organization_id", "status"),)

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[AnomalyType] = mapped_column(str_enum(AnomalyType), nullable=False)
    severity: Mapped[AnomalySeverity] = mapped_column(str_enum(AnomalySeverity), nullable=False)
    status: Mapped[AnomalyStatus] = mapped_column(str_enum(AnomalyStatus), default=AnomalyStatus.OPEN, nullable=False)
    location_event_id: Mapped[int | None] = mapped_column(ForeignKey("location_events.id", ondelete="SET NULL"), nullable=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_records.id", ondelete="SET NULL"), nullable=True)
    work_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    hr_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
