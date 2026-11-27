"""Schedule resolution and shift-instance materialisation (timezone + overnight aware)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.timeutils import ensure_utc, local_date, local_to_utc
from app.models import (
    Employee,
    Organization,
    OrganizationSettings,
    ScheduleAssignment,
    ScheduleDay,
    WorkSchedule,
)


@dataclass(frozen=True)
class ShiftInstance:
    work_date: date
    timezone: str
    schedule_id: int | None
    start: datetime
    end: datetime
    break_start: datetime | None
    break_end: datetime | None
    grace_period_minutes: int
    early_leave_grace_minutes: int
    overtime_threshold_minutes: int
    window_start: datetime
    window_end: datetime
    unscheduled: bool = False

    @property
    def scheduled_minutes(self) -> int:
        if self.unscheduled:
            return 0
        total = int((self.end - self.start).total_seconds() // 60)
        if self.break_start and self.break_end:
            total -= int((self.break_end - self.break_start).total_seconds() // 60)
        return max(0, total)

    def in_window(self, t: datetime) -> bool:
        return self.window_start <= t <= self.window_end

    def in_break(self, t: datetime, tolerance_minutes: int) -> bool:
        if not (self.break_start and self.break_end):
            return False
        tol = timedelta(minutes=tolerance_minutes)
        return self.break_start - tol <= t <= self.break_end


def employee_timezone(db: Session, employee: Employee) -> str:
    if employee.primary_office is not None:
        return employee.primary_office.timezone
    org = db.get(Organization, employee.organization_id)
    return org.timezone if org else "UTC"


def resolve_schedule(db: Session, employee: Employee, on: date) -> WorkSchedule | None:
    active = (ScheduleAssignment.effective_from <= on) & or_(ScheduleAssignment.effective_to.is_(None), ScheduleAssignment.effective_to >= on)
    base = select(ScheduleAssignment).join(WorkSchedule).where(
        ScheduleAssignment.organization_id == employee.organization_id, WorkSchedule.is_active.is_(True), active
    )
    own = db.scalars(base.where(ScheduleAssignment.employee_id == employee.id).order_by(ScheduleAssignment.effective_from.desc(), ScheduleAssignment.id.desc())).first()
    if own:
        return own.schedule
    if employee.department_id:
        dept = db.scalars(base.where(ScheduleAssignment.department_id == employee.department_id).order_by(ScheduleAssignment.effective_from.desc(), ScheduleAssignment.id.desc())).first()
        if dept:
            return dept.schedule
    return None


def _shift_on(schedule: WorkSchedule, day: date, tz: str, pre: int, post: int) -> ShiftInstance | None:
    sday: ScheduleDay | None = next((d for d in schedule.days if d.weekday == day.weekday()), None)
    if sday is None or not sday.is_working_day or sday.start_time is None or sday.end_time is None:
        return None
    start = local_to_utc(day, sday.start_time, tz)
    end_day = day + timedelta(days=1) if sday.end_time <= sday.start_time else day
    end = local_to_utc(end_day, sday.end_time, tz)
    b_start = b_end = None
    if sday.break_start and sday.break_end:
        bs_day = day + timedelta(days=1) if sday.break_start < sday.start_time else day
        be_day = bs_day + timedelta(days=1) if sday.break_end <= sday.break_start else bs_day
        b_start, b_end = local_to_utc(bs_day, sday.break_start, tz), local_to_utc(be_day, sday.break_end, tz)
    return ShiftInstance(
        work_date=day, timezone=tz, schedule_id=schedule.id, start=start, end=end, break_start=b_start, break_end=b_end,
        grace_period_minutes=schedule.grace_period_minutes, early_leave_grace_minutes=schedule.early_leave_grace_minutes,
        overtime_threshold_minutes=schedule.overtime_threshold_minutes,
        window_start=start - timedelta(minutes=pre), window_end=end + timedelta(minutes=post),
    )


def shift_for_date(db: Session, employee: Employee, day: date, settings: OrganizationSettings) -> ShiftInstance | None:
    schedule = resolve_schedule(db, employee, day)
    if schedule is None:
        return None
    tz = employee_timezone(db, employee)
    return _shift_on(schedule, day, tz, settings.pre_shift_tracking_minutes, settings.post_shift_tracking_minutes)


def shift_for_instant(db: Session, employee: Employee, t: datetime, settings: OrganizationSettings) -> ShiftInstance | None:
    """The shift whose tracking window contains t (yesterday's overnight shift is considered)."""
    t = ensure_utc(t)
    tz = employee_timezone(db, employee)
    today = local_date(t, tz)
    candidates = [s for d in (today - timedelta(days=1), today) if (s := shift_for_date(db, employee, d, settings)) and s.in_window(t)]
    if not candidates:
        return None
    # Prefer the shift whose working hours contain t, else the later (upcoming) one.
    for s in candidates:
        if s.start <= t <= s.end:
            return s
    return candidates[-1]


def next_shift(db: Session, employee: Employee, t: datetime, settings: OrganizationSettings, days: int = 7) -> ShiftInstance | None:
    tz = employee_timezone(db, employee)
    today = local_date(t, tz)
    for i in range(-1, days):
        s = shift_for_date(db, employee, today + timedelta(days=i), settings)
        if s and s.window_end >= t:
            return s
    return None


def unscheduled_shift(db: Session, employee: Employee, t: datetime, settings: OrganizationSettings) -> ShiftInstance | None:
    """Attendance without a scheduled shift (policy allow_unscheduled_attendance). Only on days that have no
    scheduled shift at all; the window is the employee's local calendar day."""
    from app.core.timeutils import day_bounds_utc

    if not settings.allow_unscheduled_attendance:
        return None
    t = ensure_utc(t)
    tz = employee_timezone(db, employee)
    day = local_date(t, tz)
    if shift_for_date(db, employee, day, settings) is not None:
        return None  # a scheduled shift exists today (t is just outside its window)
    prev = shift_for_date(db, employee, day - timedelta(days=1), settings)
    if prev is not None and prev.in_window(t):
        return None
    start, end = day_bounds_utc(day, tz)
    return ShiftInstance(work_date=day, timezone=tz, schedule_id=None, start=start, end=end, break_start=None, break_end=None,
                         grace_period_minutes=0, early_leave_grace_minutes=0, overtime_threshold_minutes=0,
                         window_start=start, window_end=end, unscheduled=True)


def attendance_shift(db: Session, employee: Employee, t: datetime, settings: OrganizationSettings) -> ShiftInstance | None:
    """ShiftCalculationService entry point: scheduled shift containing t, else an unscheduled day if allowed."""
    return shift_for_instant(db, employee, t, settings) or unscheduled_shift(db, employee, t, settings)
