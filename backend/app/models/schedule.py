from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.models.enums import AbsenceType, RequestStatus
from app.models.mixins import IdMixin, OrgScopedMixin, TimestampMixin, str_enum


class WorkSchedule(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "work_schedules"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        CheckConstraint("grace_period_minutes >= 0", name="grace_positive"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    grace_period_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    early_leave_grace_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_threshold_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    days: Mapped[list[ScheduleDay]] = relationship(back_populates="schedule", cascade="all, delete-orphan", lazy="selectin", order_by="ScheduleDay.weekday")


class ScheduleDay(IdMixin, Base):
    """Shift definition for one weekday. end_time <= start_time means an overnight shift."""

    __tablename__ = "schedule_days"
    __table_args__ = (
        UniqueConstraint("schedule_id", "weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
    )

    schedule_id: Mapped[int] = mapped_column(ForeignKey("work_schedules.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    schedule: Mapped[WorkSchedule] = relationship(back_populates="days")


class ScheduleAssignment(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    """Assigns a schedule to one employee or to a whole department. Employee assignments win."""

    __tablename__ = "schedule_assignments"
    __table_args__ = (
        CheckConstraint("(employee_id IS NULL) <> (department_id IS NULL)", name="one_target"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="date_order"),
    )

    schedule_id: Mapped[int] = mapped_column(ForeignKey("work_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    schedule: Mapped[WorkSchedule] = relationship(lazy="joined")


class LeaveRequest(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    """Leave / sick leave / business trip request. Only APPROVED requests affect attendance."""

    __tablename__ = "leave_requests"
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="period_order"),)

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[AbsenceType] = mapped_column(str_enum(AbsenceType), nullable=False)
    status: Mapped[RequestStatus] = mapped_column(str_enum(RequestStatus), default=RequestStatus.PENDING, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


AbsencePeriod = LeaveRequest  # backwards-compatible alias used by services
