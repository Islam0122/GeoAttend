"""Pure attendance metric calculation. Given sessions/breaks -> minutes + status."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.enums import (
    AttendanceStatus,
    BreakType,
    SessionConfirmation,
    SessionStatus,
)

COUNTED = {SessionConfirmation.AUTO_CONFIRMED, SessionConfirmation.CONFIRMED}
LIVE = {SessionStatus.OPEN, SessionStatus.AWAY}


@dataclass
class BreakData:
    type: BreakType
    is_paid: bool
    started_at: datetime
    ended_at: datetime | None


@dataclass
class SessionData:
    confirmation: SessionConfirmation
    status: SessionStatus
    check_in_at: datetime
    check_out_at: datetime | None
    breaks: list[BreakData] = field(default_factory=list)


@dataclass
class DayPolicy:
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    scheduled_minutes: int
    grace_period_minutes: int = 0
    early_leave_grace_minutes: int = 0
    overtime_threshold_minutes: int = 0
    half_day_ratio: float = 0.5
    count_temporary_exit_as_work: bool = False
    unscheduled: bool = False


@dataclass
class Metrics:
    actual_check_in: datetime | None
    actual_check_out: datetime | None
    late_minutes: int
    early_departure_minutes: int
    worked_minutes: int
    break_minutes: int
    overtime_minutes: int
    status: AttendanceStatus
    early_arrival_minutes: int = 0
    presence_minutes: int = 0          # physically inside the office (sessions minus every exit interval)
    temporary_exit_minutes: int = 0    # away during sessions (lunch, errands, meetings; excludes business trips)


def _minutes(td_seconds: float) -> int:
    return max(0, int(td_seconds // 60))


def _unpaid(b: BreakData, count_temp: bool) -> bool:
    if b.is_paid or b.type == BreakType.BUSINESS_TRIP:
        return False
    if b.type == BreakType.TEMPORARY_EXIT and count_temp:
        return False
    return True


def compute(
    sessions: list[SessionData],
    policy: DayPolicy,
    *,
    now: datetime,
    finalized: bool,
    on_leave: bool,
    signal_available: bool,
) -> Metrics:
    counted = sorted((s for s in sessions if s.confirmation in COUNTED), key=lambda s: s.check_in_at)
    pending = [s for s in sessions if s.confirmation == SessionConfirmation.PENDING]

    worked_s = 0.0
    break_s = 0.0
    presence_s = 0.0
    away_s = 0.0
    for s in counted:
        end = s.check_out_at or now
        if end <= s.check_in_at:
            continue
        worked_s += (end - s.check_in_at).total_seconds()
        presence_s += (end - s.check_in_at).total_seconds()
        for b in s.breaks:
            b_end = min(b.ended_at or now, end)
            b_start = max(b.started_at, s.check_in_at)
            if b_end <= b_start:
                continue
            presence_s -= (b_end - b_start).total_seconds()
            if b.type != BreakType.BUSINESS_TRIP:
                away_s += (b_end - b_start).total_seconds()
            if _unpaid(b, policy.count_temporary_exit_as_work):
                dur = (b_end - b_start).total_seconds()
                break_s += dur
                worked_s -= dur

    first_in = counted[0].check_in_at if counted else None
    any_live = any(s.status in LIVE for s in counted)
    closed_outs = [s.check_out_at for s in counted if s.check_out_at is not None]
    last_out = max(closed_outs) if closed_outs and not any_live else None

    late = 0
    if first_in and policy.scheduled_start:
        late = _minutes((first_in - policy.scheduled_start - timedelta(minutes=policy.grace_period_minutes)).total_seconds())

    early_arrival = 0
    if first_in and policy.scheduled_start:
        early_arrival = _minutes((policy.scheduled_start - first_in).total_seconds())

    early = 0
    if last_out and policy.scheduled_end:
        early = _minutes((policy.scheduled_end - timedelta(minutes=policy.early_leave_grace_minutes) - last_out).total_seconds())

    worked = _minutes(worked_s)
    overtime = 0
    if policy.scheduled_minutes > 0:
        overtime = max(0, worked - policy.scheduled_minutes - policy.overtime_threshold_minutes)

    day_over = finalized or (policy.scheduled_end is not None and now >= policy.scheduled_end and not any_live)

    if not counted:
        if pending:
            status = AttendanceStatus.PENDING_CONFIRMATION
        elif on_leave:
            status = AttendanceStatus.ON_LEAVE
        elif signal_available:
            status = AttendanceStatus.ABSENT
        else:
            # Never mark absent purely because location signals were unavailable.
            status = AttendanceStatus.LOCATION_UNAVAILABLE
    elif finalized and (any_live or any(s.status == SessionStatus.PENDING_CHECKOUT for s in counted)):
        status = AttendanceStatus.INCOMPLETE
    elif day_over and policy.scheduled_minutes > 0 and worked < policy.scheduled_minutes * policy.half_day_ratio:
        status = AttendanceStatus.HALF_DAY
    elif policy.unscheduled or policy.scheduled_start is None:
        status = AttendanceStatus.UNSCHEDULED
    elif late > 0:
        status = AttendanceStatus.LATE
    else:
        status = AttendanceStatus.PRESENT

    return Metrics(
        actual_check_in=first_in,
        actual_check_out=last_out,
        late_minutes=late,
        early_departure_minutes=early,
        worked_minutes=worked,
        break_minutes=_minutes(break_s),
        overtime_minutes=overtime,
        status=status,
        early_arrival_minutes=early_arrival,
        presence_minutes=_minutes(presence_s),
        temporary_exit_minutes=_minutes(away_s),
    )
