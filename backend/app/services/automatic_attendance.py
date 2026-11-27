"""AutomaticAttendanceService — turns *confirmed* geofence transitions into attendance.

Inputs are server-side facts only: transitions confirmed by the hysteresis engine (entry needs
`entry_confirmation_count` agreeing readings, exit needs `exit_confirmation_count`), the employee's assigned
offices that contain the current reading, the shift and the organization policy. Missing GPS is never
treated as an exit: without readings there are no transitions, so sessions are only closed by explicit
actions or by the scheduled jobs (maximum absence, shift end + timeout).

Every decision is written to `GeofenceTransition.attendance_effect` (the presence-event log).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Employee, GeofenceTransition, LocationEvent, OrganizationSettings
from app.models.enums import AttendanceEffect, DetectionMethod, SessionStatus, TransitionType
from app.services import attendance_service as att
from app.services.schedule_service import ShiftInstance

log = logging.getLogger("geoattend.auto")


def choose_office(employee: Employee, inside_office_ids: set[int], live_office_id: int | None) -> int | None:
    """Overlapping geofences: primary office first, then the office already holding the session."""
    if not inside_office_ids:
        return None
    if employee.primary_office_id in inside_office_ids:
        return employee.primary_office_id
    if live_office_id in inside_office_ids:
        return live_office_id
    return min(inside_office_ids)


def apply_enter(db: Session, employee: Employee, tr: GeofenceTransition, shift: ShiftInstance, now: datetime,
                inside_office_ids: set[int], settings: OrganizationSettings | None = None, event: LocationEvent | None = None) -> str:
    settings = settings or att.org_settings(db, employee.organization_id)
    t = tr.occurred_at
    live = att.live_session(db, employee.id)
    chosen = choose_office(employee, inside_office_ids | {tr.office_id}, live.office_id if live else None)

    if live is not None and live.record.work_date != shift.work_date:
        att.close_stale_live_session(db, live, now)
        live = None

    if live is not None:
        if live.status == SessionStatus.OPEN:
            if live.office_id == tr.office_id:
                return _set(tr, None)
            if live.office_id in inside_office_ids:  # still inside the session's office (overlap) -> keep it
                return _set(tr, AttendanceEffect.IGNORED_OVERLAP)
            att.switch_office(db, live, tr.office_id, t, now)
            return _set(tr, AttendanceEffect.OFFICE_SWITCH)
        # AWAY (temporary exit / lunch / trip)
        brk = att._open_break(live)  # noqa: SLF001
        expired = brk is not None and t > brk.expires_at
        if not expired and settings.automatic_resume_enabled:
            switched = live.office_id != tr.office_id
            att.resume_session(db, live, t, now, office_id=tr.office_id)
            return _set(tr, AttendanceEffect.RETURN_TO_OFFICE, "office switch" if switched else None)
        # Resume disabled or absence longer than allowed: the session ended at the exit time.
        att.end_absence_without_resume(db, live, now)
        live = None

    if tr.office_id != chosen:
        return _set(tr, AttendanceEffect.IGNORED_OVERLAP)
    if not settings.automatic_checkin_enabled:
        return _set(tr, AttendanceEffect.CHECKIN_DISABLED)
    att.start_session(db, employee, office_id=tr.office_id, at=t, shift=shift, now=now, detection=DetectionMethod.AUTOMATIC,
                      explicit=False, transition=tr, event=event)
    return _set(tr, AttendanceEffect.AUTO_CHECKIN)


def apply_exit(db: Session, employee: Employee, tr: GeofenceTransition, now: datetime, inside_office_ids: set[int],
               settings: OrganizationSettings | None = None) -> str:
    settings = settings or att.org_settings(db, employee.organization_id)
    live = att.live_session(db, employee.id)
    if live is None or live.office_id != tr.office_id or live.status != SessionStatus.OPEN:
        return _set(tr, AttendanceEffect.NO_ACTIVE_SESSION)
    other = inside_office_ids - {tr.office_id}
    if other:  # walked straight into another assigned office: one session, office switch
        target = choose_office(employee, other, None)
        att.switch_office(db, live, target, tr.occurred_at, now)
        return _set(tr, AttendanceEffect.OFFICE_SWITCH, f"to office {target}")
    if not settings.automatic_checkout_enabled:
        return _set(tr, AttendanceEffect.CHECKOUT_DISABLED)
    return _set(tr, AttendanceEffect(att.record_exit(db, employee, live, tr.occurred_at, now, tr)))


def apply_transitions(db: Session, employee: Employee, transitions: list[GeofenceTransition], shift: ShiftInstance,
                      settings: OrganizationSettings, now: datetime, inside_office_ids: set[int], enabled: bool,
                      event: LocationEvent | None = None) -> list[str]:
    """Exits first so a move between offices is handled before the corresponding entry."""
    effects: list[str] = []
    for tr in sorted(transitions, key=lambda x: 0 if x.type == TransitionType.EXIT else 1):
        if not enabled:
            effects.append(_set(tr, AttendanceEffect.PRESENCE_ONLY))
            continue
        if tr.type == TransitionType.EXIT:
            effects.append(apply_exit(db, employee, tr, now, inside_office_ids, settings))
        else:
            effects.append(apply_enter(db, employee, tr, shift, now, inside_office_ids, settings, event))
        log.info("geofence_transition", extra={"employee_id": employee.id, "office_id": tr.office_id, "type": tr.type.value,
                                               "effect": tr.attendance_effect, "occurred_at": tr.occurred_at.isoformat()})
    return [e for e in effects if e]


def _set(tr: GeofenceTransition, effect: AttendanceEffect | None, note: str | None = None) -> str:
    tr.attendance_effect = effect.value if effect else None
    if note:
        tr.note = note
    return tr.attendance_effect or ""
