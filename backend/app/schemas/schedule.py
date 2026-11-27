from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AbsenceType, RequestStatus
from app.schemas.common import ORMModel


class ScheduleDayIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    is_working_day: bool = True
    start_time: time | None = None
    end_time: time | None = None
    break_start: time | None = None
    break_end: time | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.is_working_day and (self.start_time is None or self.end_time is None):
            raise ValueError("Working days need start_time and end_time")
        if self.start_time is not None and self.start_time == self.end_time:
            raise ValueError("start_time and end_time must differ")
        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("Provide both break_start and break_end or neither")
        return self


class ScheduleDayOut(ORMModel, ScheduleDayIn):
    id: int


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    grace_period_minutes: int = Field(default=10, ge=0, le=240)
    early_leave_grace_minutes: int = Field(default=0, ge=0, le=240)
    overtime_threshold_minutes: int = Field(default=0, ge=0, le=600)
    is_active: bool = True
    days: list[ScheduleDayIn] = []

    @model_validator(mode="after")
    def _unique_days(self):
        if len({d.weekday for d in self.days}) != len(self.days):
            raise ValueError("Duplicate weekday")
        return self


class SchedulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    grace_period_minutes: int | None = Field(default=None, ge=0, le=240)
    early_leave_grace_minutes: int | None = Field(default=None, ge=0, le=240)
    overtime_threshold_minutes: int | None = Field(default=None, ge=0, le=600)
    is_active: bool | None = None
    days: list[ScheduleDayIn] | None = None


class ScheduleOut(ORMModel):
    id: int
    name: str
    grace_period_minutes: int
    early_leave_grace_minutes: int
    overtime_threshold_minutes: int
    is_active: bool
    days: list[ScheduleDayOut]


class AssignmentIn(BaseModel):
    schedule_id: int
    employee_id: int | None = None
    department_id: int | None = None
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _target(self):
        if (self.employee_id is None) == (self.department_id is None):
            raise ValueError("Provide exactly one of employee_id or department_id")
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to before effective_from")
        return self


class AssignmentOut(ORMModel):
    id: int
    schedule_id: int
    employee_id: int | None
    department_id: int | None
    effective_from: date
    effective_to: date | None


class ShiftOut(BaseModel):
    work_date: date
    start: datetime
    end: datetime
    break_start: datetime | None
    break_end: datetime | None
    timezone: str
    schedule_id: int
    tracking_window_start: datetime
    tracking_window_end: datetime


class AbsenceIn(BaseModel):
    employee_id: int | None = None  # HR may create for others; employees for themselves
    type: AbsenceType
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _order(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AbsenceOut(ORMModel):
    id: int
    employee_id: int
    employee_name: str | None = None
    type: AbsenceType
    status: RequestStatus
    starts_at: datetime
    ends_at: datetime
    reason: str | None
    reviewed_at: datetime | None


class ReviewIn(BaseModel):
    approve: bool
    comment: str | None = Field(default=None, max_length=2000)
