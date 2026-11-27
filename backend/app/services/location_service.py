"""GPS geofencing engine: ingestion, validation, hysteresis, transitions -> attendance."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import ensure_utc
from app.models import (
    AttendanceSession,
    DeviceRegistration,
    Employee,
    GeofenceState,
    GeofenceTransition,
    LocationConsent,
    LocationEvent,
    Office,
    OfficeAssignment,
    OfficeGeofence,
    OrganizationSettings,
)
from app.models.enums import (
    AnomalySeverity,
    AnomalyType,
    EventProcessingStatus,
    AttendanceMode,
    GeofencePresence,
    LocationEventType,
    TransitionType,
    Zone,
)
from app.schemas.location import LocationEventIn
from app.services import attendance_service as att
from app.services import automatic_attendance as auto_att
from app.services import geo
from app.services.anomalies import raise_anomaly
from app.services.schedule_service import ShiftInstance, attendance_shift

log = logging.getLogger("geoattend.geofence")

MAX_PROCESSING_ATTEMPTS = 5
MULTI_DEVICE_WINDOW = timedelta(minutes=5)


class RejectReason:
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    DEVICE_NOT_REGISTERED = "DEVICE_NOT_REGISTERED"
    OUTSIDE_TRACKING_WINDOW = "OUTSIDE_TRACKING_WINDOW"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    EVENT_TOO_OLD = "EVENT_TOO_OLD"
    EMPLOYEE_INACTIVE = "EMPLOYEE_INACTIVE"
    DETECTION_DISABLED = "DETECTION_DISABLED"


PERMISSION_REJECTS = {RejectReason.CONSENT_REQUIRED, RejectReason.DEVICE_NOT_REGISTERED, RejectReason.EMPLOYEE_INACTIVE}


@dataclass
class EventResult:
    client_event_id: str | None
    result: str  # ACCEPTED | LOW_ACCURACY | OUT_OF_ORDER | SUSPICIOUS | NO_OFFICE | PENDING | DUPLICATE | REJECTED
    reason: str | None = None
    event_id: int | None = None
    office_id: int | None = None
    distance_m: float | None = None
    accuracy_m: float | None = None
    zone: str | None = None
    transition: str | None = None
    attendance_status: str | None = None
    session_id: int | None = None
    work_date: str | None = None
    effects: list[str] | None = None            # attendance effects produced by this reading
    confirmation: dict | None = None            # {"target": "INSIDE", "readings": 1, "required": 2}

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ helpers ----

def consent_granted_at(db: Session, employee_id: int, t: datetime) -> bool:
    latest = db.scalar(select(LocationConsent).where(LocationConsent.employee_id == employee_id, LocationConsent.created_at <= t + timedelta(seconds=get_settings().max_clock_skew_seconds))
                       .order_by(LocationConsent.created_at.desc(), LocationConsent.id.desc()).limit(1))
    return bool(latest and latest.granted)


def current_consent(db: Session, employee_id: int) -> LocationConsent | None:
    return db.scalar(select(LocationConsent).where(LocationConsent.employee_id == employee_id).order_by(LocationConsent.created_at.desc(), LocationConsent.id.desc()).limit(1))


def candidate_offices(db: Session, employee: Employee) -> list[Office]:
    q = select(Office).join(OfficeGeofence).where(Office.organization_id == employee.organization_id, Office.is_active.is_(True), OfficeGeofence.enabled.is_(True))
    assigned = db.scalars(q.join(OfficeAssignment, OfficeAssignment.office_id == Office.id).where(OfficeAssignment.employee_id == employee.id)).unique().all()
    if assigned:
        return list(assigned)
    if employee.primary_office_id:
        return [o for o in db.scalars(q.where(Office.id == employee.primary_office_id)).unique().all()]
    # No assignment means NO_OFFICE: an employee is never silently validated against arbitrary offices.
    return []


def lock_employee(db: Session, employee_id: int) -> Employee | None:
    """Serialize all attendance mutations per employee: SELECT ... FOR UPDATE OF employees (PostgreSQL row lock).
    Eager joins are disabled for the lock query (FOR UPDATE cannot target the nullable side of an outer join)."""
    db.execute(select(Employee.id).where(Employee.id == employee_id).with_for_update(of=Employee))
    return db.get(Employee, employee_id)


_lock_employee = lock_employee


def _result_from_event(ev: LocationEvent, result: str | None = None) -> EventResult:
    return EventResult(client_event_id=ev.client_event_id, result=result or ev.processing_status.value, reason=ev.status_reason, event_id=ev.id,
                       office_id=ev.office_id, distance_m=round(ev.distance_m, 1) if ev.distance_m is not None else None, accuracy_m=ev.accuracy_m,
                       zone=ev.zone.value if ev.zone else None, transition=ev.transition.value if ev.transition else None,
                       work_date=ev.work_date.isoformat() if ev.work_date else None)


# ------------------------------------------------------------------ ingest ----

def ingest(db: Session, employee_id: int, items: list[LocationEventIn], now: datetime) -> list[EventResult]:
    """Process events in recorded_at order (offline batches arrive out of order). Each event commits separately."""
    results: list[EventResult] = []
    for item in sorted(items, key=lambda i: ensure_utc(i.recorded_at)):
        try:
            res = _ingest_one(db, employee_id, item, now)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - never lose an accepted fix because downstream logic failed
            db.rollback()
            log.exception("location_processing_failed", extra={"employee_id": employee_id, "client_event_id": item.client_event_id})
            res = _store_pending(db, employee_id, item, now, str(exc))
        results.append(res)
    return results


def _store_pending(db: Session, employee_id: int, item: LocationEventIn, now: datetime, error: str) -> EventResult:
    try:
        emp = db.get(Employee, employee_id)
        assert emp is not None
        ev = _new_event(emp, item, now, None)
        ev.processing_status, ev.processing_attempts, ev.status_reason = EventProcessingStatus.PENDING, 1, f"deferred: {error[:150]}"
        db.add(ev)
        db.commit()
        return EventResult(client_event_id=item.client_event_id, result="PENDING", reason="DEFERRED", event_id=ev.id)
    except IntegrityError:
        db.rollback()
        ev = db.scalar(select(LocationEvent).where(LocationEvent.employee_id == employee_id, LocationEvent.client_event_id == item.client_event_id))
        return _result_from_event(ev, "DUPLICATE") if ev else EventResult(item.client_event_id, "REJECTED", "PROCESSING_ERROR")


def _new_event(emp: Employee, item: LocationEventIn, now: datetime, device: DeviceRegistration | None) -> LocationEvent:
    return LocationEvent(
        organization_id=emp.organization_id, employee_id=emp.id, device_registration_id=device.id if device else None,
        client_event_id=item.client_event_id, device_id=item.device_id, platform=item.platform, permission_status=item.permission_status,
        trigger=item.trigger, latitude=item.latitude, longitude=item.longitude, accuracy_m=item.accuracy, is_mocked=item.is_mocked,
        recorded_at=ensure_utc(item.recorded_at), received_at=now,
    )


def _ingest_one(db: Session, employee_id: int, item: LocationEventIn, now: datetime) -> EventResult:
    emp = _lock_employee(db, employee_id)
    if emp is None or not emp.is_active:
        return EventResult(item.client_event_id, "REJECTED", RejectReason.EMPLOYEE_INACTIVE)
    settings = att.org_settings(db, emp.organization_id)
    outcome = admit_event(db, emp, item, now, settings, LocationEventType.PRESENCE)
    if isinstance(outcome, EventResult):
        return outcome
    ev, shift = outcome
    return evaluate_event(db, emp, ev, shift, settings, now)


def admit_event(db: Session, emp: Employee, item: LocationEventIn, now: datetime, settings: OrganizationSettings,
                event_type: LocationEventType) -> EventResult | tuple[LocationEvent, ShiftInstance]:
    """Shared server-side validation for every GPS fix (presence, check-in, check-out).
    Returns a rejection/duplicate result, or the stored event and its shift."""
    recorded_at = ensure_utc(item.recorded_at)

    # 1. Idempotency
    existing = db.scalar(select(LocationEvent).where(LocationEvent.employee_id == emp.id, LocationEvent.client_event_id == item.client_event_id))
    if existing is not None:
        return _result_from_event(existing, "DUPLICATE")

    # 2. Coordinate / accuracy / timestamp validation (never stored when invalid)
    reason = geo.validate_coordinates(item.latitude, item.longitude) or geo.validate_accuracy(item.accuracy, settings.max_reasonable_accuracy_m)
    if reason is None and recorded_at > now + timedelta(seconds=get_settings().max_clock_skew_seconds):
        reason = RejectReason.FUTURE_TIMESTAMP
    if reason is None and now - recorded_at > timedelta(hours=settings.max_event_age_hours):
        reason = RejectReason.EVENT_TOO_OLD
    if reason:
        return EventResult(item.client_event_id, "REJECTED", reason)

    # 3. Consent at the time of recording
    if not consent_granted_at(db, emp.id, recorded_at):
        return EventResult(item.client_event_id, "REJECTED", RejectReason.CONSENT_REQUIRED)

    # 4. Device registration
    device = db.scalar(select(DeviceRegistration).where(DeviceRegistration.employee_id == emp.id, DeviceRegistration.device_id == item.device_id, DeviceRegistration.is_active.is_(True)))
    if device is None:
        other = db.scalar(select(DeviceRegistration).where(DeviceRegistration.organization_id == emp.organization_id, DeviceRegistration.device_id == item.device_id, DeviceRegistration.employee_id != emp.id, DeviceRegistration.is_active.is_(True)))
        wd = att.work_date_for(db, emp, recorded_at, settings)
        if other is not None:
            raise_anomaly(db, org_id=emp.organization_id, employee_id=emp.id, type=AnomalyType.SHARED_DEVICE, severity=AnomalySeverity.HIGH,
                          work_date=wd, details={"device_id": item.device_id, "registered_to_employee_id": other.employee_id})
        if settings.require_registered_device:
            return EventResult(item.client_event_id, "REJECTED", RejectReason.DEVICE_NOT_REGISTERED)
        raise_anomaly(db, org_id=emp.organization_id, employee_id=emp.id, type=AnomalyType.UNREGISTERED_DEVICE, severity=AnomalySeverity.WARNING,
                      work_date=wd, details={"device_id": item.device_id})
    else:
        device.last_seen_at = max(device.last_seen_at or recorded_at, recorded_at)
        device.location_permission = item.permission_status

    # 5. Privacy: only inside the configured working windows (or the unscheduled day, if the policy allows it)
    if event_type == LocationEventType.PRESENCE and not settings.automatic_detection_enabled:
        return EventResult(item.client_event_id, "REJECTED", RejectReason.DETECTION_DISABLED)
    shift = attendance_shift(db, emp, recorded_at, settings)
    if shift is None:
        return EventResult(item.client_event_id, "REJECTED", RejectReason.OUTSIDE_TRACKING_WINDOW)

    # 6. Same device + same fix timestamp = retransmission under a new id
    dup = db.scalar(select(LocationEvent).where(LocationEvent.employee_id == emp.id, LocationEvent.device_id == item.device_id, LocationEvent.recorded_at == recorded_at))
    if dup is not None:
        return _result_from_event(dup, "DUPLICATE")

    ev = _new_event(emp, item, now, device)
    ev.work_date = shift.work_date
    ev.event_type = event_type
    try:
        with db.begin_nested():
            db.add(ev)
            db.flush()
    except IntegrityError:  # concurrent request with the same client_event_id
        existing = db.scalar(select(LocationEvent).where(LocationEvent.employee_id == emp.id, LocationEvent.client_event_id == item.client_event_id))
        return _result_from_event(existing, "DUPLICATE") if existing else EventResult(item.client_event_id, "REJECTED", "CONFLICT")
    return ev, shift


def evaluate_event(db: Session, emp: Employee, ev: LocationEvent, shift: ShiftInstance, settings: OrganizationSettings, now: datetime,
                   apply_attendance: bool | None = None) -> EventResult:
    """Server-side evaluation of a stored event. Also used to retry deferred (PENDING) events."""
    ev.processing_attempts += 1
    att.expire_due_breaks(db, emp.id, ev.recorded_at, now)

    # Spoofing indicators -> excluded from attendance, routed to HR review (no automatic penalty)
    if ev.is_mocked:
        return _suspicious(db, emp, ev, "MOCK_LOCATION_FLAG", AnomalyType.MOCK_LOCATION, AnomalySeverity.HIGH, {"platform": ev.platform.value})

    prev = db.scalar(select(LocationEvent).where(
        LocationEvent.employee_id == emp.id, LocationEvent.id != ev.id, LocationEvent.latitude.is_not(None),
        LocationEvent.processing_status.in_([EventProcessingStatus.ACCEPTED, EventProcessingStatus.LOW_ACCURACY]),
    ).order_by(LocationEvent.recorded_at.desc()).limit(1))
    if prev is not None:
        if ev.recorded_at <= prev.recorded_at:
            ev.processing_status, ev.status_reason = EventProcessingStatus.OUT_OF_ORDER, "older than last applied reading"
            _evaluate_zone_only(db, emp, ev)
            return _result_from_event(ev)
        dist, speed = geo.implied_speed_mps(prev.latitude, prev.longitude, prev.recorded_at, ev.latitude, ev.longitude, ev.recorded_at)  # type: ignore[arg-type]
        if geo.is_suspicious_jump(dist, speed, prev.accuracy_m, ev.accuracy_m, settings.max_speed_mps):
            return _suspicious(db, emp, ev, "IMPOSSIBLE_SPEED", AnomalyType.IMPOSSIBLE_SPEED, AnomalySeverity.WARNING,
                               {"distance_m": round(dist, 1), "speed_mps": round(speed, 1) if speed != float("inf") else None,
                                "previous_event_id": prev.id, "seconds": (ev.recorded_at - prev.recorded_at).total_seconds()})
        if prev.device_id != ev.device_id and ev.recorded_at - prev.recorded_at < MULTI_DEVICE_WINDOW:
            raise_anomaly(db, org_id=emp.organization_id, employee_id=emp.id, type=AnomalyType.MULTIPLE_DEVICES, severity=AnomalySeverity.WARNING,
                          location_event_id=ev.id, work_date=shift.work_date, details={"devices": [prev.device_id, ev.device_id]})

    offices = candidate_offices(db, emp)
    if not offices:
        ev.processing_status, ev.status_reason = EventProcessingStatus.NO_OFFICE, "no active geofence"
        return _result_from_event(ev)

    readings = []
    for office in offices:
        fence = office.geofence
        d = geo.haversine_m(ev.latitude, ev.longitude, office.latitude, office.longitude)  # type: ignore[arg-type]
        z = geo.classify(d, ev.accuracy_m, geo.FenceParams(fence.radius_m, fence.max_accuracy_m, fence.entry_buffer_m, fence.exit_buffer_m))
        readings.append((office, d, z))
    live = att.live_session(db, emp.id)
    inside_ids = {o.id for o, _, z in readings if z == Zone.INSIDE}
    chosen = auto_att.choose_office(emp, inside_ids, live.office_id if live else None)
    primary = next((r for r in readings if r[0].id == chosen), None) or min(readings, key=lambda r: r[1])
    ev.office_id, ev.distance_m, ev.zone = primary[0].id, primary[1], primary[2]
    ev.processing_status = EventProcessingStatus.ACCEPTED if ev.accuracy_m <= primary[0].geofence.max_accuracy_m else EventProcessingStatus.LOW_ACCURACY
    if ev.processing_status == EventProcessingStatus.LOW_ACCURACY:
        ev.status_reason = "accuracy above geofence maximum"

    transitions: list[GeofenceTransition] = []
    policy_counts = settings.attendance_mode != AttendanceMode.MANUAL
    confirmation: dict | None = None
    for office, d, z in readings:
        state = _state_for(db, emp, office.id)
        stale = state.last_recorded_at is None or state.last_recorded_at < shift.window_start
        if stale and not (live and live.office_id == office.id):
            state.presence, state.candidate, state.candidate_count, state.candidate_since = GeofencePresence.UNKNOWN, None, 0, None
        before = state.presence
        cfg = (geo.StabilityConfig(office.geofence.required_consecutive, 0, settings.entry_confirmation_count, settings.exit_confirmation_count)
               if policy_counts else geo.StabilityConfig(office.geofence.required_consecutive, office.geofence.stability_window_seconds))
        res = geo.step(geo.PresenceState(state.presence, state.candidate, state.candidate_count, state.candidate_since), z, ev.recorded_at, cfg)
        reading = GeofencePresence.INSIDE if z == Zone.INSIDE else GeofencePresence.OUTSIDE if z == Zone.OUTSIDE else None
        continuing = reading is not None and state.candidate == reading and state.candidate_count > 0
        first_event_id = state.candidate_first_event_id if continuing else ev.id
        readings_count = state.candidate_count + 1 if continuing else 1
        if res.state.candidate is not None:
            state.candidate_first_event_id = first_event_id
        state.presence, state.candidate, state.candidate_count, state.candidate_since = res.state.presence, res.state.candidate, res.state.candidate_count, res.state.candidate_since
        state.last_recorded_at, state.last_zone, state.last_distance_m, state.last_accuracy_m = ev.recorded_at, z, d, ev.accuracy_m
        state.last_event_type = ev.event_type.value
        if z == Zone.INSIDE:
            state.last_inside_at = ev.recorded_at
        if z in (Zone.INSIDE, Zone.OUTSIDE) and (state.last_validated_at is None or ev.recorded_at >= state.last_validated_at):
            # Server-validated presence for monitoring: this single reading passed coordinate, consent, device,
            # window, spoofing and accuracy checks, and the conservative rule classified it unambiguously.
            state.last_validated_at, state.last_validated_zone = ev.recorded_at, z
            state.last_validated_distance_m, state.last_validated_accuracy_m = d, ev.accuracy_m
        if office.id == primary[0].id and res.state.candidate is not None:
            confirmation = {"target": res.state.candidate.value, "readings": res.state.candidate_count, "required": cfg.required_for(res.state.candidate)}
        if res.confirmed is None:
            continue
        ttype = None
        if res.confirmed == GeofencePresence.INSIDE and before != GeofencePresence.INSIDE and office.geofence.entry_detection_enabled:
            ttype = TransitionType.ENTER
        elif res.confirmed == GeofencePresence.OUTSIDE and before == GeofencePresence.INSIDE and office.geofence.exit_detection_enabled:
            ttype = TransitionType.EXIT
        if ttype is None:
            continue
        tr = GeofenceTransition(organization_id=emp.organization_id, employee_id=emp.id, office_id=office.id, type=ttype,
                                occurred_at=res.occurred_at or ev.recorded_at, confirmed_at=ev.recorded_at, first_event_id=first_event_id,
                                confirming_event_id=ev.id, readings=readings_count,
                                details={"distance_m": round(d, 1), "accuracy_m": ev.accuracy_m, "radius_m": office.geofence.radius_m})
        db.add(tr)
        transitions.append(tr)
    db.flush()

    enabled = settings.automatic_attendance if apply_attendance is None else apply_attendance
    effects = auto_att.apply_transitions(db, emp, transitions, shift, settings, now, inside_ids, enabled, ev)
    for tr in transitions:
        if tr.office_id == ev.office_id or ev.transition is None:
            ev.transition = tr.type
    session: AttendanceSession | None = None
    res_out = _result_from_event(ev)
    res_out.effects, res_out.confirmation = effects, confirmation
    live = att.live_session(db, emp.id) or session
    if live is not None:
        res_out.session_id = live.id
        res_out.attendance_status = live.record.status.value
    return res_out


def _evaluate_zone_only(db: Session, emp: Employee, ev: LocationEvent) -> None:
    """Annotate an out-of-order event with distance/zone for history, without touching the state machine."""
    offices = candidate_offices(db, emp)
    if not offices:
        return
    best = min(((o, geo.haversine_m(ev.latitude, ev.longitude, o.latitude, o.longitude)) for o in offices), key=lambda r: r[1])  # type: ignore[arg-type]
    f = best[0].geofence
    ev.office_id, ev.distance_m = best[0].id, best[1]
    ev.zone = geo.classify(best[1], ev.accuracy_m, geo.FenceParams(f.radius_m, f.max_accuracy_m, f.entry_buffer_m, f.exit_buffer_m))


def _suspicious(db: Session, emp: Employee, ev: LocationEvent, reason: str, atype: AnomalyType, sev: AnomalySeverity, details: dict) -> EventResult:
    ev.processing_status, ev.status_reason = EventProcessingStatus.SUSPICIOUS, reason
    db.flush()
    raise_anomaly(db, org_id=emp.organization_id, employee_id=emp.id, type=atype, severity=sev, location_event_id=ev.id, work_date=ev.work_date, details=details)
    _evaluate_zone_only(db, emp, ev)
    return _result_from_event(ev)


def _state_for(db: Session, emp: Employee, office_id: int) -> GeofenceState:
    st = db.scalar(select(GeofenceState).where(GeofenceState.employee_id == emp.id, GeofenceState.office_id == office_id))
    if st is None:
        st = GeofenceState(organization_id=emp.organization_id, employee_id=emp.id, office_id=office_id, presence=GeofencePresence.UNKNOWN, candidate_count=0)
        try:
            with db.begin_nested():
                db.add(st)
                db.flush()
        except IntegrityError:
            st = db.scalar(select(GeofenceState).where(GeofenceState.employee_id == emp.id, GeofenceState.office_id == office_id))
            assert st is not None
    return st


# ------------------------------------------------------- deferred processing ----

def reprocess_pending(db: Session, now: datetime, min_age_seconds: int = 30, limit: int = 500) -> dict[str, int]:
    """Retry events whose processing failed earlier (in recorded_at order per employee)."""
    stats = {"processed": 0, "failed": 0, "dropped": 0}
    cutoff = now - timedelta(seconds=min_age_seconds)
    ids = db.scalars(select(LocationEvent.id).where(
        LocationEvent.processing_status == EventProcessingStatus.PENDING, LocationEvent.received_at <= cutoff,
        LocationEvent.processing_attempts < MAX_PROCESSING_ATTEMPTS,
    ).order_by(LocationEvent.employee_id, LocationEvent.recorded_at).limit(limit)).all()
    for ev_id in ids:
        ev = db.get(LocationEvent, ev_id)
        if ev is None:
            continue
        try:
            emp = _lock_employee(db, ev.employee_id)
            assert emp is not None
            settings = att.org_settings(db, emp.organization_id)
            shift = attendance_shift(db, emp, ev.recorded_at, settings)
            if shift is None:
                ev.processing_status, ev.status_reason = EventProcessingStatus.NO_OFFICE, "outside tracking window on reprocess"
                ev.latitude = ev.longitude = None
                ev.coordinates_purged = True
                stats["dropped"] += 1
            else:
                ev.work_date = shift.work_date
                evaluate_event(db, emp, ev, shift, settings, now)
                stats["processed"] += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            ev = db.get(LocationEvent, ev_id)
            if ev is not None:
                ev.processing_attempts += 1
                ev.status_reason = f"retry failed: {str(exc)[:150]}"
                if ev.processing_attempts >= MAX_PROCESSING_ATTEMPTS:
                    raise_anomaly(db, org_id=ev.organization_id, employee_id=ev.employee_id, type=AnomalyType.PROCESSING_ERROR,
                                  severity=AnomalySeverity.WARNING, location_event_id=ev.id, work_date=ev.work_date, details={"error": str(exc)[:300]})
                db.commit()
            stats["failed"] += 1
            log.exception("location_reprocess_failed", extra={"event_id": ev_id})
    return stats


def live_status(db: Session, emp: Employee, now: datetime | None = None) -> dict:
    """Presence for an employee (no coordinates). Full resolver output + legacy keys. See presence_service."""
    from app.core.timeutils import utcnow
    from app.services.presence_service import resolve

    v = resolve(db, emp, now or utcnow())
    d = v.as_dict()
    d.update(presence=v.zone_status, last_zone=v.validated_zone, session_state=v.session_status,
             session_status=v.live_session_status, is_away=v.session_status == "TEMPORARY_EXIT")
    return d
