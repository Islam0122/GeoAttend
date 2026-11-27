"""Explicit web/PWA attendance actions: GPS check-in / check-out. The server is the final authority:
coordinates are re-validated, distance and geofence membership are computed here, never trusted from the client."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceSession, Employee, LocationEvent, Office
from app.models.enums import (
    AnomalySeverity,
    AnomalyType,
    EventProcessingStatus,
    GeofencePresence,
    LocationEventType,
    SessionConfirmation,
    Zone,
)
from app.schemas.location import LocationEventIn
from app.services import attendance_service as att
from app.services import location_service as loc
from app.services.anomalies import raise_anomaly

log = logging.getLogger("geoattend.checkin")

DELAYED_SYNC_AFTER = timedelta(minutes=15)


@dataclass
class ActionResult:
    state: str               # CHECK_IN_SUCCESS | CHECK_OUT_SUCCESS | GPS_ACCURACY_LOW | OUTSIDE_GEOFENCE | CHECK_IN_FAILED | CHECK_OUT_FAILED
    code: str                # machine-readable reason
    message: str
    http_status: int
    client_event_id: str | None = None
    event_id: int | None = None
    office_id: int | None = None
    office_name: str | None = None
    radius_m: float | None = None
    max_accuracy_m: float | None = None
    distance_m: float | None = None
    accuracy_m: float | None = None
    zone: str | None = None
    session_id: int | None = None
    record_id: int | None = None
    attendance_status: str | None = None
    pending_approval: bool = False
    recorded_at: datetime | None = None
    received_at: datetime | None = None
    duplicate: bool = False

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("http_status")
        return d


REJECT_MESSAGES = {
    "CONSENT_REQUIRED": "Please allow location use for attendance first.",
    "DEVICE_NOT_REGISTERED": "This browser is not registered. Reload the page and try again.",
    "OUTSIDE_TRACKING_WINDOW": "Check-in is only possible during your scheduled working window.",
    "FUTURE_TIMESTAMP": "Your device clock looks wrong. Fix the time and retry.",
    "EVENT_TOO_OLD": "This offline check-in is too old to be accepted. Request a correction instead.",
    "INVALID_COORDINATES": "The browser returned an invalid location. Please retry.",
    "COORDINATES_OUT_OF_RANGE": "The browser returned an invalid location. Please retry.",
    "NULL_ISLAND": "The browser could not determine your location. Please retry.",
    "INVALID_ACCURACY": "The browser returned an invalid accuracy. Please retry.",
    "ACCURACY_UNREASONABLE": "GPS accuracy is too low. Move near a window or outdoors and retry.",
    "EMPLOYEE_INACTIVE": "Your employee profile is inactive.",
}


def _office_info(res: ActionResult, office: Office | None) -> None:
    if office is not None:
        res.office_id, res.office_name = office.id, office.name
        res.radius_m, res.max_accuracy_m = office.geofence.radius_m, office.geofence.max_accuracy_m


def _from_event(db: Session, ev: LocationEvent, res: ActionResult) -> ActionResult:
    res.event_id, res.client_event_id = ev.id, ev.client_event_id
    res.distance_m = round(ev.distance_m, 1) if ev.distance_m is not None else None
    res.accuracy_m, res.zone = ev.accuracy_m, ev.zone.value if ev.zone else None
    res.recorded_at, res.received_at = ev.recorded_at, ev.received_at
    _office_info(res, db.get(Office, ev.office_id) if ev.office_id else None)
    return res


def _replay(db: Session, ev: LocationEvent, action: LocationEventType) -> ActionResult:
    """Same event_uuid submitted again (retry / offline queue resend): return the original outcome."""
    col = AttendanceSession.check_in_event_id if action == LocationEventType.CHECK_IN else AttendanceSession.check_out_event_id
    session = db.scalar(select(AttendanceSession).where(col == ev.id))
    ok_state = "CHECK_IN_SUCCESS" if action == LocationEventType.CHECK_IN else "CHECK_OUT_SUCCESS"
    if session is not None:
        res = ActionResult(ok_state, "DUPLICATE", "Already recorded.", 200, duplicate=True, session_id=session.id, record_id=session.record_id,
                           attendance_status=session.record.status.value, pending_approval=session.confirmation == SessionConfirmation.PENDING)
    else:
        code = ev.status_reason or "CHECK_FAILED"
        state = code if code in ("GPS_ACCURACY_LOW", "OUTSIDE_GEOFENCE") else ("CHECK_IN_FAILED" if action == LocationEventType.CHECK_IN else "CHECK_OUT_FAILED")
        res = ActionResult(state, code, "This attempt was already evaluated and was not accepted.", 422, duplicate=True)
    return _from_event(db, ev, res)


def perform(db: Session, employee_id: int, item: LocationEventIn, action: LocationEventType, now: datetime) -> ActionResult:
    failed = "CHECK_IN_FAILED" if action == LocationEventType.CHECK_IN else "CHECK_OUT_FAILED"
    emp = loc.lock_employee(db, employee_id)
    if emp is None or not emp.is_active:
        return ActionResult(failed, "EMPLOYEE_INACTIVE", REJECT_MESSAGES["EMPLOYEE_INACTIVE"], 403, client_event_id=item.client_event_id)
    settings = att.org_settings(db, emp.organization_id)

    existing = db.scalar(select(LocationEvent).where(LocationEvent.employee_id == emp.id, LocationEvent.client_event_id == item.client_event_id))
    if existing is not None:
        return _replay(db, existing, action)

    outcome = loc.admit_event(db, emp, item, now, settings, action)
    if isinstance(outcome, loc.EventResult):
        if outcome.result == "DUPLICATE":
            ev = db.get(LocationEvent, outcome.event_id)
            return _replay(db, ev, action) if ev else ActionResult(failed, "DUPLICATE", "Duplicate event.", 409)
        code = outcome.reason or "REJECTED"
        status = 403 if code in loc.PERMISSION_REJECTS else 422
        return ActionResult(failed, code, REJECT_MESSAGES.get(code, "Location could not be validated."), status, client_event_id=item.client_event_id)
    ev, shift = outcome

    # Server-side evaluation (spoofing indicators, distance, zone, geofence state). Attendance is driven below, not by transitions.
    loc.evaluate_event(db, emp, ev, shift, settings, now, apply_attendance=False)
    if ev.processing_status == EventProcessingStatus.OUT_OF_ORDER and ev.zone is None:
        loc._evaluate_zone_only(db, emp, ev)  # noqa: SLF001
    res = _from_event(db, ev, ActionResult(failed, "", "", 422))

    if now - ev.recorded_at > DELAYED_SYNC_AFTER:
        raise_anomaly(db, org_id=emp.organization_id, employee_id=emp.id, type=AnomalyType.DELAYED_SYNC, severity=AnomalySeverity.INFO,
                      location_event_id=ev.id, work_date=shift.work_date,
                      details={"recorded_at": ev.recorded_at.isoformat(), "received_at": ev.received_at.isoformat(), "action": action.value})

    def fail(state: str, code: str, msg: str, http: int = 422) -> ActionResult:
        ev.status_reason = code
        res.state, res.code, res.message, res.http_status = state, code, msg, http
        log.info("gps_action_rejected", extra={"employee_id": emp.id, "action": action.value, "code": code, "distance_m": res.distance_m, "accuracy_m": res.accuracy_m})
        return res

    if ev.processing_status == EventProcessingStatus.SUSPICIOUS:
        return fail(failed, "LOCATION_SUSPICIOUS", "This location could not be verified. Retry, or ask HR to record your attendance.")
    if ev.processing_status == EventProcessingStatus.NO_OFFICE or ev.office_id is None:
        return fail(failed, "NO_OFFICE_ASSIGNED", "No active office geofence is assigned to you.")

    office = db.get(Office, ev.office_id)
    needs_fence = action == LocationEventType.CHECK_IN or settings.checkout_requires_geofence
    if needs_fence and ev.zone == Zone.UNCERTAIN:
        if ev.accuracy_m > office.geofence.max_accuracy_m:
            return fail("GPS_ACCURACY_LOW", "GPS_ACCURACY_LOW",
                        f"GPS accuracy is ±{round(ev.accuracy_m)} m; at most ±{round(office.geofence.max_accuracy_m)} m is required. Move near a window or outdoors and retry.")
        return fail("GPS_ACCURACY_LOW", "GEOFENCE_BOUNDARY",
                    "You are near the edge of the office zone and the GPS reading is not precise enough to confirm. Move closer and retry.")
    if needs_fence and ev.zone == Zone.OUTSIDE:
        return fail("OUTSIDE_GEOFENCE", "OUTSIDE_GEOFENCE",
                    f"You are about {round(ev.distance_m or 0)} m from {office.name}; check-in requires being within {round(office.geofence.radius_m)} m.")

    try:
        if action == LocationEventType.CHECK_IN:
            session = att.explicit_check_in(db, emp, office_id=office.id, at=ev.recorded_at, shift=shift, event_id=ev.id, now=now)
        else:
            session = att.explicit_check_out(db, emp, at=ev.recorded_at, event_id=ev.id, now=now)
    except att.AttendanceError as exc:
        return fail(failed, exc.code.upper(), str(exc), 409)

    ev.status_reason = "ACCEPTED"
    state = loc._state_for(db, emp, office.id)  # noqa: SLF001 - server-validated presence
    if action == LocationEventType.CHECK_IN:
        state.presence, state.last_inside_at = GeofencePresence.INSIDE, ev.recorded_at
    elif ev.zone == Zone.OUTSIDE:
        state.presence = GeofencePresence.OUTSIDE
    state.candidate, state.candidate_count, state.candidate_since = None, 0, None
    res.state = "CHECK_IN_SUCCESS" if action == LocationEventType.CHECK_IN else "CHECK_OUT_SUCCESS"
    res.code, res.http_status = "OK", 201
    res.session_id, res.record_id = session.id, session.record_id
    res.attendance_status = session.record.status.value
    res.pending_approval = session.confirmation == SessionConfirmation.PENDING
    res.message = ("Check-in recorded and sent for manager approval." if res.pending_approval else
                   "You checked in successfully." if action == LocationEventType.CHECK_IN else "You checked out successfully.")
    return res


def detect_repeated_failures(db: Session, now: datetime, window_minutes: int = 30, threshold: int = 5) -> int:
    """Suspicious pattern: many rejected check-in attempts in a short window (e.g. location probing)."""
    from sqlalchemy import func

    since = now - timedelta(minutes=window_minutes)
    rows = db.execute(select(LocationEvent.employee_id, LocationEvent.organization_id, func.count()).where(
        LocationEvent.event_type == LocationEventType.CHECK_IN, LocationEvent.received_at >= since,
        LocationEvent.status_reason.in_(["OUTSIDE_GEOFENCE", "GPS_ACCURACY_LOW", "GEOFENCE_BOUNDARY", "LOCATION_SUSPICIOUS"]),
    ).group_by(LocationEvent.employee_id, LocationEvent.organization_id)).all()
    n = 0
    for emp_id, org_id, count in rows:
        if count >= threshold:
            emp = db.get(Employee, emp_id)
            from app.core.timeutils import local_date
            from app.services.schedule_service import employee_timezone

            wd = local_date(now, employee_timezone(db, emp)) if emp else None
            if raise_anomaly(db, org_id=org_id, employee_id=emp_id, type=AnomalyType.REPEATED_FAILED_CHECKIN, severity=AnomalySeverity.WARNING,
                             work_date=wd, details={"attempts": count, "window_minutes": window_minutes}):
                n += 1
    db.commit()
    return n
