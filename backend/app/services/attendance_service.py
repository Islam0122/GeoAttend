"""Hybrid attendance engine: turns confirmed geofence transitions into sessions/records.

All mutating functions expect to run inside the caller's transaction; the caller holds
the per-employee row lock (see location_service) so session creation/closing is serialized.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.timeutils import ensure_utc
from app.models import (
    AbsencePeriod,
    AttendanceBreak,
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSession,
    DeviceRegistration,
    Employee,
    GeofenceState,
    GeofenceTransition,
    LocationEvent,
    OrganizationSettings,
    User,
    WorkSchedule,
)
from app.models.enums import (
    AttendanceEffect,
    BreakOutcome,
    DetectionMethod,
    AbsenceType,
    AnomalySeverity,
    AnomalyType,
    AttendanceStatus,
    BreakType,
    CheckoutPolicy,
    CloseReason,
    ConfirmationPolicy,
    CorrectionType,
    EventProcessingStatus,
    PermissionStatus,
    RequestStatus,
    SessionConfirmation,
    SessionSource,
    SessionStatus,
)
from app.services import calculation as calc
from app.services.anomalies import raise_anomaly
from app.services.audit import audit
from app.services.notifications import notify_employee
from app.services.schedule_service import ShiftInstance, shift_for_date

log = logging.getLogger("geoattend.attendance")

LIVE = (SessionStatus.OPEN, SessionStatus.AWAY)


class AttendanceError(Exception):
    def __init__(self, message: str, code: str = "attendance_error"):
        super().__init__(message)
        self.code = code


def org_settings(db: Session, org_id: int) -> OrganizationSettings:
    s = db.get(OrganizationSettings, org_id)
    if s is None:
        s = OrganizationSettings(organization_id=org_id)
        db.add(s)
        db.flush()
    return s


def _fmt_local(t: datetime, tz: str) -> str:
    from app.core.timeutils import get_zone

    return ensure_utc(t).astimezone(get_zone(tz)).strftime("%H:%M")


# ------------------------------------------------------------------ records ----

def get_or_create_record(db: Session, employee: Employee, shift: ShiftInstance, office_id: int | None = None) -> AttendanceRecord:
    rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == employee.id, AttendanceRecord.work_date == shift.work_date))
    if rec:
        if office_id and rec.office_id is None:
            rec.office_id = office_id
        if rec.is_unscheduled and not shift.unscheduled:  # a schedule was assigned later: adopt it
            rec.is_unscheduled, rec.schedule_id = False, shift.schedule_id
            rec.scheduled_start, rec.scheduled_end, rec.scheduled_minutes = shift.start, shift.end, shift.scheduled_minutes
            rec.grace_period_minutes = shift.grace_period_minutes
        return rec
    rec = AttendanceRecord(
        organization_id=employee.organization_id, employee_id=employee.id, work_date=shift.work_date,
        office_id=office_id or employee.primary_office_id, schedule_id=shift.schedule_id, timezone=shift.timezone,
        scheduled_start=None if shift.unscheduled else shift.start, scheduled_end=None if shift.unscheduled else shift.end,
        scheduled_minutes=shift.scheduled_minutes, grace_period_minutes=shift.grace_period_minutes, status=AttendanceStatus.ABSENT,
        is_unscheduled=shift.unscheduled,
    )
    try:
        with db.begin_nested():
            db.add(rec)
            db.flush()
    except IntegrityError:
        # Concurrent creator won the race; use its row.
        rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == employee.id, AttendanceRecord.work_date == shift.work_date))
        assert rec is not None
    return rec


def live_session(db: Session, employee_id: int) -> AttendanceSession | None:
    return db.scalar(select(AttendanceSession).where(AttendanceSession.employee_id == employee_id, AttendanceSession.status.in_(LIVE)))


def _open_break(session: AttendanceSession) -> AttendanceBreak | None:
    return next((b for b in session.breaks if b.ended_at is None), None)


def has_leave(db: Session, employee_id: int, start: datetime | None, end: datetime | None) -> bool:
    if not start or not end:
        return False
    return bool(db.scalar(select(exists().where(
        AbsencePeriod.employee_id == employee_id, AbsencePeriod.status == RequestStatus.APPROVED,
        AbsencePeriod.type.in_([AbsenceType.LEAVE, AbsenceType.SICK]),
        AbsencePeriod.starts_at < end, AbsencePeriod.ends_at > start))))


def business_trip_at(db: Session, employee_id: int, t: datetime) -> AbsencePeriod | None:
    return db.scalar(select(AbsencePeriod).where(
        AbsencePeriod.employee_id == employee_id, AbsencePeriod.status == RequestStatus.APPROVED,
        AbsencePeriod.type == AbsenceType.BUSINESS_TRIP, AbsencePeriod.starts_at <= t, AbsencePeriod.ends_at > t))


def signal_available(db: Session, employee_id: int, start: datetime, end: datetime) -> bool:
    """Did we have a usable location signal for this employee during the window?"""
    had_events = db.scalar(select(exists().where(
        LocationEvent.employee_id == employee_id, LocationEvent.recorded_at >= start, LocationEvent.recorded_at <= end,
        LocationEvent.processing_status.in_([EventProcessingStatus.ACCEPTED, EventProcessingStatus.LOW_ACCURACY, EventProcessingStatus.OUT_OF_ORDER]))))
    if had_events:
        return True
    return bool(db.scalar(select(exists().where(
        DeviceRegistration.employee_id == employee_id, DeviceRegistration.is_active.is_(True),
        DeviceRegistration.location_permission.in_([PermissionStatus.GRANTED_ALWAYS, PermissionStatus.GRANTED_WHEN_IN_USE]),
        DeviceRegistration.last_seen_at >= start, DeviceRegistration.last_seen_at <= end))))


def recompute(db: Session, record: AttendanceRecord, now: datetime) -> AttendanceRecord:
    settings = org_settings(db, record.organization_id)
    schedule = db.get(WorkSchedule, record.schedule_id) if record.schedule_id else None
    db.flush()
    db.refresh(record, attribute_names=["sessions"])
    sessions = [
        calc.SessionData(
            confirmation=s.confirmation, status=s.status, check_in_at=s.check_in_at, check_out_at=s.check_out_at,
            breaks=[calc.BreakData(b.type, b.is_paid, b.started_at, b.ended_at) for b in s.breaks],
        )
        for s in record.sessions
    ]
    policy = calc.DayPolicy(
        scheduled_start=record.scheduled_start, scheduled_end=record.scheduled_end, scheduled_minutes=record.scheduled_minutes,
        grace_period_minutes=record.grace_period_minutes,
        early_leave_grace_minutes=schedule.early_leave_grace_minutes if schedule else 0,
        overtime_threshold_minutes=schedule.overtime_threshold_minutes if schedule else 0,
        half_day_ratio=settings.half_day_ratio, count_temporary_exit_as_work=settings.count_temporary_exit_as_work,
    )
    policy.unscheduled = record.is_unscheduled
    m = calc.compute(sessions, policy, now=now, finalized=record.is_finalized,
                     on_leave=has_leave(db, record.employee_id, record.scheduled_start, record.scheduled_end),
                     signal_available=record.signal_available)
    record.actual_check_in = m.actual_check_in
    record.actual_check_out = m.actual_check_out
    record.late_minutes = m.late_minutes
    record.early_departure_minutes = m.early_departure_minutes
    record.worked_minutes = m.worked_minutes
    record.break_minutes = m.break_minutes
    record.overtime_minutes = m.overtime_minutes
    record.early_arrival_minutes = m.early_arrival_minutes
    record.presence_minutes = m.presence_minutes
    record.temporary_exit_minutes = m.temporary_exit_minutes
    record.status = m.status
    counted = [x for x in record.sessions if x.confirmation != SessionConfirmation.REJECTED]
    record.is_confirmed = bool(counted) and all(x.confirmation in calc.COUNTED and x.status != SessionStatus.PENDING_CHECKOUT for x in counted)
    for x in record.sessions:
        x.duration_minutes = session_net_minutes(x, settings.count_temporary_exit_as_work) if x.check_out_at else None
        x.gross_minutes = int((x.check_out_at - x.check_in_at).total_seconds() // 60) if x.check_out_at else None
        for b in x.breaks:
            b.duration_minutes = int((b.ended_at - b.started_at).total_seconds() // 60) if b.ended_at and b.outcome == BreakOutcome.RETURNED else None
    return record


def session_net_minutes(s: AttendanceSession, count_temp: bool) -> int:
    """Session length minus unpaid breaks (whole minutes)."""
    end = s.check_out_at
    if end is None:
        return 0
    total = (end - s.check_in_at).total_seconds()
    for b in s.breaks:
        if b.is_paid or b.type == BreakType.BUSINESS_TRIP or (b.type == BreakType.TEMPORARY_EXIT and count_temp):
            continue
        b_end = min(b.ended_at or end, end)
        if b_end > b.started_at:
            total -= (b_end - max(b.started_at, s.check_in_at)).total_seconds()
    return max(0, int(total // 60))


def initial_confirmation(settings: OrganizationSettings, explicit: bool) -> SessionConfirmation:
    """AUTOMATIC: confirmed by server validation. EMPLOYEE_CONFIRMATION: an explicit check-in *is* the
    employee's confirmation; auto-detected arrivals wait for it. MANAGER_APPROVAL: always waits for a manager."""
    policy = settings.confirmation_policy
    if policy == ConfirmationPolicy.AUTOMATIC:
        return SessionConfirmation.AUTO_CONFIRMED
    if policy == ConfirmationPolicy.EMPLOYEE_CONFIRMATION:
        return SessionConfirmation.CONFIRMED if explicit else SessionConfirmation.PENDING
    return SessionConfirmation.PENDING


# ----------------------------------------------------------------- sessions ----

def close_session(db: Session, session: AttendanceSession, at: datetime, reason: CloseReason, settings: OrganizationSettings,
                  now: datetime, *, force_pending: bool = False) -> None:
    at = max(ensure_utc(at), session.check_in_at)
    for b in session.breaks:
        if b.ended_at is None:  # temporary exits are never deleted; they are closed with an explicit outcome
            b.ended_at = max(at, b.started_at)
            b.outcome = BreakOutcome.SESSION_CLOSED
    session.check_out_at = at
    session.checkout_detected_at = now
    session.close_reason = reason
    if force_pending or settings.checkout_policy == CheckoutPolicy.REQUIRE_CONFIRMATION:
        session.status = SessionStatus.PENDING_CHECKOUT
    else:
        session.status = SessionStatus.CLOSED
    db.flush()


def _expire_break(db: Session, session: AttendanceSession, brk: AttendanceBreak, settings: OrganizationSettings, now: datetime) -> None:
    if brk.type == BreakType.BUSINESS_TRIP:
        brk.ended_at, brk.outcome = brk.expires_at, BreakOutcome.SESSION_CLOSED
        close_session(db, session, brk.expires_at, CloseReason.BUSINESS_TRIP_END, settings, now)
        return
    started = brk.started_at
    reason = CloseReason.TEMPORARY_EXIT_EXPIRED if brk.type == BreakType.TEMPORARY_EXIT else CloseReason.BREAK_NOT_RETURNED
    # Employee did not come back within the maximum absence: the working session ended when they left.
    # The exit interval is kept (outcome NOT_RETURNED, no return time) for the audit trail.
    brk.ended_at, brk.outcome = started, BreakOutcome.NOT_RETURNED
    db.flush()
    close_session(db, session, started, reason, settings, now)


def expire_due_breaks(db: Session, employee_id: int, at: datetime, now: datetime) -> int:
    """Resolve AWAY sessions whose break expired before `at` (event time or wall clock)."""
    session = live_session(db, employee_id)
    if session is None or session.status != SessionStatus.AWAY:
        return 0
    brk = _open_break(session)
    if brk is None or brk.expires_at >= at:
        return 0
    settings = org_settings(db, session.organization_id)
    _expire_break(db, session, brk, settings, now)
    recompute(db, session.record, now)
    log.info("break_expired", extra={"employee_id": employee_id, "session_id": session.id, "break_type": brk.type})
    return 1


def start_session(db: Session, employee: Employee, *, office_id: int, at: datetime, shift: ShiftInstance, now: datetime,
                  detection: DetectionMethod, explicit: bool, transition: GeofenceTransition | None = None,
                  event: LocationEvent | None = None) -> AttendanceSession:
    """Create a live session (atomic: the partial unique index rejects a concurrent second live session)."""
    settings = org_settings(db, employee.organization_id)
    record = get_or_create_record(db, employee, shift, office_id)
    record.signal_available = True
    confirmation = initial_confirmation(settings, explicit=explicit)
    session = AttendanceSession(
        organization_id=employee.organization_id, record_id=record.id, employee_id=employee.id, office_id=office_id,
        status=SessionStatus.OPEN, source=SessionSource.GPS, confirmation=confirmation, check_in_at=at,
        detected_at=transition.confirmed_at if transition else now, confirmed_at=now if confirmation == SessionConfirmation.CONFIRMED else None,
        enter_transition_id=transition.id if transition else None, check_in_event_id=event.id if event and explicit else None,
        detection_method=detection.value, check_in_accuracy_m=event.accuracy_m if event else None,
        check_in_device_id=event.device_id if event else None,
    )
    db.add(session)
    db.flush()
    recompute(db, record, now)
    when = _fmt_local(at, record.timezone)
    if confirmation == SessionConfirmation.PENDING and settings.confirmation_policy == ConfirmationPolicy.MANAGER_APPROVAL:
        notify_employee(db, employee, type="ARRIVAL_PENDING_APPROVAL", title="Arrival recorded",
                        body=f"Arrival at {when} is waiting for manager approval.", data={"record_id": record.id, "session_id": session.id})
    elif confirmation == SessionConfirmation.PENDING:
        notify_employee(db, employee, type="CONFIRM_ARRIVAL", title="Confirm your arrival",
                        body=f"We detected you at the office at {when}. Tap to confirm.", data={"record_id": record.id, "session_id": session.id})
    else:
        late = f" ({record.late_minutes} min late)" if record.late_minutes else ""
        verb = "Work started automatically" if detection == DetectionMethod.AUTOMATIC else "You checked in"
        notify_employee(db, employee, type="CHECK_IN", title="Checked in" if explicit else "Arrival detected",
                        body=f"{verb} at {when}{late}. If this is wrong you can dispute it.", data={"record_id": record.id, "session_id": session.id})
    log.info("session_opened", extra={"employee_id": employee.id, "session_id": session.id, "detection": detection.value, "office_id": office_id})
    return session


def resume_session(db: Session, session: AttendanceSession, at: datetime, now: datetime, *, office_id: int | None = None) -> AttendanceSession:
    """Close the open temporary exit (RETURN_TO_OFFICE). Short exits within the grace period are counted as work."""
    settings = org_settings(db, session.organization_id)
    brk = _open_break(session)
    if brk is not None:
        brk.ended_at, brk.outcome = max(at, brk.started_at), BreakOutcome.RETURNED
        away_min = (brk.ended_at - brk.started_at).total_seconds() / 60
        if brk.type == BreakType.TEMPORARY_EXIT and away_min <= settings.temporary_exit_grace_minutes:
            brk.is_paid = True
    session.status = SessionStatus.OPEN
    if office_id is not None and office_id != session.office_id:
        session.office_id = office_id
    db.flush()
    recompute(db, session.record, now)
    log.info("session_resumed", extra={"employee_id": session.employee_id, "session_id": session.id})
    return session


def switch_office(db: Session, session: AttendanceSession, office_id: int, at: datetime, now: datetime) -> AttendanceSession:
    """Moving between assigned offices keeps ONE session; the switch is recorded on the transition (OFFICE_SWITCH)."""
    if session.status == SessionStatus.AWAY:
        return resume_session(db, session, at, now, office_id=office_id)
    session.office_id = office_id
    db.flush()
    return session


def end_absence_without_resume(db: Session, session: AttendanceSession, now: datetime) -> None:
    """Automatic resume disabled: the working session ended when the employee left."""
    brk = _open_break(session)
    settings = org_settings(db, session.organization_id)
    if brk is not None:
        _expire_break(db, session, brk, settings, now)
    recompute(db, session.record, now)


def close_stale_live_session(db: Session, live: AttendanceSession, now: datetime) -> None:
    """A live session from a previous shift that was never closed (e.g. browser closed overnight)."""
    settings = org_settings(db, live.organization_id)
    close_session(db, live, live.check_out_at or live.check_in_at, CloseReason.TRACKING_WINDOW_ENDED, settings, now, force_pending=True)
    recompute(db, live.record, now)


def record_exit(db: Session, employee: Employee, live: AttendanceSession, t: datetime, now: datetime,
                transition: GeofenceTransition | None = None) -> str:
    """Confirmed exit from the session's office. Returns the attendance effect.
    Never ends the working day just because the employee stepped out: before (shift end - checkout grace)
    it is a TEMPORARY_EXIT that is resolved by RETURN_TO_OFFICE or by the maximum-absence rule."""
    settings = org_settings(db, employee.organization_id)
    record = live.record
    shift = shift_for_date(db, employee, record.work_date, settings) if not record.is_unscheduled else None
    if transition is not None:
        live.exit_transition_id = transition.id
    trip = business_trip_at(db, employee.id, t)
    final_after = record.scheduled_end - timedelta(minutes=settings.checkout_grace_minutes) if record.scheduled_end else None
    if trip is not None:
        end = min(trip.ends_at, record.scheduled_end) if record.scheduled_end else trip.ends_at
        live.breaks.append(AttendanceBreak(organization_id=employee.organization_id, type=BreakType.BUSINESS_TRIP, is_paid=True, started_at=t,
                                           expires_at=max(end, t), detection_method=DetectionMethod.AUTOMATIC.value, outcome=BreakOutcome.OPEN))
        live.status = SessionStatus.AWAY
        effect = AttendanceEffect.TEMPORARY_EXIT
    elif shift is not None and shift.in_break(t, settings.lunch_detection_tolerance_minutes):
        live.breaks.append(AttendanceBreak(organization_id=employee.organization_id, type=BreakType.LUNCH, is_paid=False, started_at=t,
                                           expires_at=shift.break_end + timedelta(minutes=settings.temporary_exit_max_minutes),  # type: ignore[operator]
                                           detection_method=DetectionMethod.AUTOMATIC.value, outcome=BreakOutcome.OPEN))
        live.status = SessionStatus.AWAY
        effect = AttendanceEffect.TEMPORARY_EXIT
    elif final_after is not None and t >= final_after:
        close_session(db, live, t, CloseReason.GEOFENCE_EXIT, settings, now)
        effect = AttendanceEffect.FINAL_CHECKOUT
    else:
        live.breaks.append(AttendanceBreak(organization_id=employee.organization_id, type=BreakType.TEMPORARY_EXIT,
                                           is_paid=settings.count_temporary_exit_as_work, started_at=t,
                                           expires_at=t + timedelta(minutes=settings.temporary_exit_max_minutes),
                                           detection_method=DetectionMethod.AUTOMATIC.value, outcome=BreakOutcome.OPEN))
        live.status = SessionStatus.AWAY
        effect = AttendanceEffect.TEMPORARY_EXIT
    db.flush()
    recompute(db, record, now)
    if live.status == SessionStatus.PENDING_CHECKOUT:
        notify_employee(db, employee, type="CONFIRM_CHECKOUT", title="Confirm your checkout",
                        body=f"We detected you left the office at {_fmt_local(t, record.timezone)}. Tap to confirm.",
                        data={"record_id": record.id, "session_id": live.id})
    elif live.status == SessionStatus.CLOSED:
        notify_employee(db, employee, type="CHECK_OUT", title="Work day completed",
                        body=f"Departure recorded at {_fmt_local(t, record.timezone)}. Worked {record.worked_minutes // 60}h {record.worked_minutes % 60}m.",
                        data={"record_id": record.id, "session_id": live.id})
    log.info("geofence_exit_handled", extra={"employee_id": employee.id, "session_id": live.id, "effect": effect.value})
    return effect.value


# Backwards-compatible wrappers (legacy hybrid mode / existing callers)
def handle_enter(db: Session, employee: Employee, transition: GeofenceTransition, shift: ShiftInstance, now: datetime) -> AttendanceSession | None:
    from app.services.automatic_attendance import apply_enter

    apply_enter(db, employee, transition, shift, now, inside_office_ids={transition.office_id})
    return live_session(db, employee.id)


def handle_exit(db: Session, employee: Employee, transition: GeofenceTransition, now: datetime) -> AttendanceSession | None:
    live = live_session(db, employee.id)
    if live is None or live.office_id != transition.office_id or live.status != SessionStatus.OPEN:
        return None
    record_exit(db, employee, live, transition.occurred_at, now, transition)
    return live


# --------------------------------------------------------- explicit actions ----

def explicit_check_in(db: Session, employee: Employee, *, office_id: int, at: datetime, shift: ShiftInstance, event_id: int, now: datetime) -> AttendanceSession:
    """Employee pressed Check-in and the server validated they are inside `office_id`'s geofence."""
    settings = org_settings(db, employee.organization_id)
    live = live_session(db, employee.id)
    event = db.get(LocationEvent, event_id)
    if live is not None:
        if live.status == SessionStatus.AWAY:
            brk = _open_break(live)
            if brk is None or at <= brk.expires_at:
                return resume_session(db, live, at, now, office_id=office_id)
            _expire_break(db, live, brk, settings, now)
            recompute(db, live.record, now)
        elif live.record.work_date != shift.work_date:
            close_stale_live_session(db, live, now)
        else:
            raise AttendanceError("You are already checked in", "already_checked_in")
    session = start_session(db, employee, office_id=office_id, at=at, shift=shift, now=now, detection=DetectionMethod.MANUAL, explicit=True, event=event)
    session.check_in_event_id = event_id
    return session


def explicit_check_out(db: Session, employee: Employee, *, at: datetime, event_id: int | None, now: datetime) -> AttendanceSession:
    live = live_session(db, employee.id)
    if live is None:
        raise AttendanceError("You are not checked in", "not_checked_in")
    settings = org_settings(db, employee.organization_id)
    close_session(db, live, at, CloseReason.EMPLOYEE_CHECKOUT, settings, now)
    live.status = SessionStatus.CLOSED  # an explicit checkout is its own confirmation
    live.checkout_confirmed_at = now
    live.check_out_event_id = event_id
    recompute(db, live.record, now)
    notify_employee(db, employee, type="CHECK_OUT", title="Checked out",
                    body=f"Checked out at {_fmt_local(at, live.record.timezone)}. Today: {live.record.worked_minutes // 60}h {live.record.worked_minutes % 60:02d}m.",
                    data={"record_id": live.record_id, "session_id": live.id})
    return live


def start_break(db: Session, employee: Employee, *, kind: BreakType, at: datetime, now: datetime) -> AttendanceSession:
    live = live_session(db, employee.id)
    if live is None or live.status != SessionStatus.OPEN:
        raise AttendanceError("Check in before starting a break", "not_checked_in" if live is None else "already_on_break")
    settings = org_settings(db, employee.organization_id)
    if kind == BreakType.BUSINESS_TRIP:
        raise AttendanceError("Business trips are registered as approved leave requests", "invalid_break")
    shift = shift_for_date(db, employee, live.record.work_date, settings)
    if kind == BreakType.LUNCH and shift and shift.break_end and at < shift.break_end:
        expires = shift.break_end + timedelta(minutes=settings.temporary_exit_max_minutes)
    else:
        expires = at + timedelta(minutes=max(settings.temporary_exit_max_minutes, 60 if kind == BreakType.LUNCH else 0))
    live.breaks.append(AttendanceBreak(organization_id=employee.organization_id, type=kind, started_at=at, expires_at=expires,
                                       is_paid=kind in (BreakType.TEMPORARY_EXIT, BreakType.PERSONAL) and settings.count_temporary_exit_as_work
                                       or kind == BreakType.MEETING,
                                       detection_method=DetectionMethod.MANUAL.value, outcome=BreakOutcome.OPEN))
    live.status = SessionStatus.AWAY
    db.flush()
    recompute(db, live.record, now)
    return live


def end_break(db: Session, employee: Employee, *, at: datetime, now: datetime) -> AttendanceSession:
    live = live_session(db, employee.id)
    brk = _open_break(live) if live is not None else None
    if live is None or brk is None:
        raise AttendanceError("No active break", "no_active_break")
    brk.ended_at, brk.outcome = max(at, brk.started_at), BreakOutcome.RETURNED
    live.status = SessionStatus.OPEN
    db.flush()
    recompute(db, live.record, now)
    return live


def approve(db: Session, record: AttendanceRecord, reviewer: User, *, approve_: bool, session_id: int | None, now: datetime) -> AttendanceRecord:
    """Manager approval of pending sessions (MANAGER_APPROVAL policy)."""
    targets = [s for s in record.sessions if s.confirmation == SessionConfirmation.PENDING and (session_id is None or s.id == session_id)]
    if not targets:
        raise AttendanceError("Nothing awaiting approval", "nothing_to_confirm")
    for s in targets:
        s.approved_by_id = reviewer.id
        if approve_:
            s.confirmation, s.confirmed_at = SessionConfirmation.CONFIRMED, now
        else:
            s.confirmation = SessionConfirmation.REJECTED
            if s.status in LIVE:
                close_session(db, s, s.check_in_at, CloseReason.MANUAL, org_settings(db, record.organization_id), now)
                s.status = SessionStatus.CLOSED
    recompute(db, record, now)
    audit(db, org_id=record.organization_id, actor_id=reviewer.id, action="attendance.approved" if approve_ else "attendance.rejected",
          entity_type="attendance_record", entity_id=record.id, changes={"sessions": [s.id for s in targets]})
    emp = db.get(Employee, record.employee_id)
    if emp:
        notify_employee(db, emp, type="ATTENDANCE_REVIEWED", title="Attendance approved" if approve_ else "Attendance rejected",
                        body=f"Your attendance for {record.work_date.isoformat()} was {'approved' if approve_ else 'rejected'}.", data={"record_id": record.id})
    return record


# ------------------------------------------------------------ confirmations ----

def confirm(db: Session, record: AttendanceRecord, user: User, *, action: str, session_id: int | None, now: datetime) -> AttendanceRecord:
    targets = [s for s in record.sessions if session_id is None or s.id == session_id]
    if session_id is not None and not targets:
        raise AttendanceError("Session not found on this record", "not_found")
    changed = 0
    for s in targets:
        if action == "CONFIRM":
            if s.confirmation == SessionConfirmation.PENDING:
                s.confirmation, s.confirmed_at = SessionConfirmation.CONFIRMED, now
                changed += 1
            if s.status == SessionStatus.PENDING_CHECKOUT:
                s.status, s.checkout_confirmed_at = SessionStatus.CLOSED, now
                changed += 1
        elif action == "REJECT":
            if s.confirmation == SessionConfirmation.PENDING:
                s.confirmation = SessionConfirmation.REJECTED
                if s.status in LIVE:
                    close_session(db, s, s.check_in_at, CloseReason.MANUAL, org_settings(db, record.organization_id), now)
                    s.status = SessionStatus.CLOSED
                changed += 1
    if not changed:
        raise AttendanceError("Nothing awaiting confirmation", "nothing_to_confirm")
    recompute(db, record, now)
    audit(db, org_id=record.organization_id, actor_id=user.id, action=f"attendance.{action.lower()}", entity_type="attendance_record",
          entity_id=record.id, changes={"session_id": session_id, "changed": changed})
    return record


# -------------------------------------------------------------- corrections ----

def apply_correction(db: Session, corr: AttendanceCorrection, reviewer: User, now: datetime) -> AttendanceRecord:
    record = db.get(AttendanceRecord, corr.record_id)
    assert record is not None
    settings = org_settings(db, record.organization_id)
    before = {"check_in": record.actual_check_in, "check_out": record.actual_check_out, "status": record.status}
    sessions = [s for s in record.sessions if s.confirmation != SessionConfirmation.REJECTED]

    if corr.type == CorrectionType.DISPUTE and not (corr.requested_check_in or corr.requested_check_out):
        for s in sessions:
            if s.status in LIVE:
                close_session(db, s, s.check_in_at, CloseReason.CORRECTION, settings, now)
            s.status, s.confirmation = SessionStatus.CLOSED, SessionConfirmation.REJECTED
    elif not sessions:
        if not (corr.requested_check_in and corr.requested_check_out):
            raise AttendanceError("Both check-in and check-out are required when no attendance exists", "invalid_correction")
        manual = AttendanceSession(
            organization_id=record.organization_id, record_id=record.id, employee_id=record.employee_id, office_id=record.office_id,
            status=SessionStatus.CLOSED, confirmation=SessionConfirmation.CONFIRMED, source=SessionSource.CORRECTION,
            check_in_at=corr.requested_check_in, check_out_at=corr.requested_check_out, confirmed_at=now,
            checkout_confirmed_at=now, close_reason=CloseReason.CORRECTION, detection_method=DetectionMethod.CORRECTION.value,
        )
        emp = db.get(Employee, record.employee_id)
        shift = shift_for_date(db, emp, record.work_date, settings) if emp else None
        if shift and shift.break_start and shift.break_end and manual.check_in_at <= shift.break_start and manual.check_out_at >= shift.break_end:
            # Scheduled lunch is unpaid for manually entered days too.
            manual.breaks.append(AttendanceBreak(organization_id=record.organization_id, type=BreakType.LUNCH, is_paid=False,
                                                 started_at=shift.break_start, ended_at=shift.break_end, expires_at=shift.break_end,
                                                 detection_method=DetectionMethod.CORRECTION.value, outcome=BreakOutcome.RETURNED))
        db.add(manual)
    else:
        first, last = sessions[0], sessions[-1]
        if corr.requested_check_in:
            first.check_in_at = corr.requested_check_in
            first.confirmation, first.confirmed_at = SessionConfirmation.CONFIRMED, now
        if corr.requested_check_out:
            for b in last.breaks:
                if b.ended_at is None or b.ended_at > corr.requested_check_out:
                    b.ended_at = max(b.started_at, min(b.ended_at or corr.requested_check_out, corr.requested_check_out))
            last.check_out_at = corr.requested_check_out
            last.status, last.close_reason, last.checkout_confirmed_at = SessionStatus.CLOSED, CloseReason.CORRECTION, now
            last.confirmation = SessionConfirmation.CONFIRMED if last.confirmation == SessionConfirmation.PENDING else last.confirmation
        for s in (first, last):
            if s.check_out_at and s.check_out_at < s.check_in_at:
                raise AttendanceError("Check-out must be after check-in", "invalid_correction")
    db.flush()
    recompute(db, record, now)
    audit(db, org_id=record.organization_id, actor_id=reviewer.id, action="attendance.correction_applied", entity_type="attendance_record",
          entity_id=record.id, changes={"correction_id": corr.id, "before": before,
                                        "after": {"check_in": record.actual_check_in, "check_out": record.actual_check_out, "status": record.status}})
    return record


# ------------------------------------------------------------- finalization ----

def close_after_tracking_window(db: Session, session: AttendanceSession, now: datetime) -> None:
    """Tracking window ended while the session was still live: we cannot know the real checkout."""
    settings = org_settings(db, session.organization_id)
    if session.status == SessionStatus.AWAY:
        brk = _open_break(session)
        if brk is not None:
            _expire_break(db, session, brk, settings, now)
            return
    state = db.scalar(select(GeofenceState).where(GeofenceState.employee_id == session.employee_id, GeofenceState.office_id == session.office_id))
    last_inside = state.last_inside_at if state and state.last_inside_at else session.check_in_at
    close_session(db, session, last_inside, CloseReason.TRACKING_WINDOW_ENDED, settings, now, force_pending=True)
    raise_anomaly(db, org_id=session.organization_id, employee_id=session.employee_id, type=AnomalyType.INCOMPLETE_SESSION,
                  severity=AnomalySeverity.INFO, record_id=session.record_id, work_date=session.record.work_date,
                  details={"session_id": session.id, "provisional_checkout": last_inside.isoformat()})
    emp = db.get(Employee, session.employee_id)
    if emp:
        notify_employee(db, emp, type="CONFIRM_CHECKOUT", title="Checkout not detected",
                        body="We could not detect when you left. Please confirm the suggested time or request a correction.",
                        data={"record_id": session.record_id, "session_id": session.id})


def finalize_day(db: Session, employee: Employee, shift: ShiftInstance, now: datetime) -> AttendanceRecord:
    record = get_or_create_record(db, employee, shift)
    if record.is_finalized:
        return recompute(db, record, now)
    live = live_session(db, employee.id)
    if live is not None and live.record_id == record.id:
        close_after_tracking_window(db, live, now)
    record.signal_available = record.signal_available or signal_available(db, employee.id, shift.window_start, shift.window_end)
    record.is_finalized = True
    recompute(db, record, now)
    if record.status == AttendanceStatus.LOCATION_UNAVAILABLE:
        raise_anomaly(db, org_id=employee.organization_id, employee_id=employee.id, type=AnomalyType.LOCATION_UNAVAILABLE,
                      severity=AnomalySeverity.INFO, record_id=record.id, work_date=record.work_date,
                      details={"message": "No location signal during the shift; attendance needs manual review."})
    return record


def work_date_for(db: Session, employee: Employee, t: datetime, settings: OrganizationSettings) -> date | None:
    from app.services.schedule_service import shift_for_instant

    s = shift_for_instant(db, employee, t, settings)
    return s.work_date if s else None
