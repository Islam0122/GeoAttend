from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    location_rate_limit,
    pagination,
    require_employee,
    require_staff,
    scope_employees,
)
from app.core import rate_limit
from app.core.db import get_db
from app.core.timeutils import utcnow
from app.models import (
    DeviceRegistration,
    Employee,
    LocationConsent,
    LocationEvent,
)
from app.models.enums import (
    AnomalySeverity,
    AnomalyType,
    EventProcessingStatus,
    PermissionStatus,
    Zone,
)
from app.schemas.common import Page
from app.schemas.location import (
    BatchResultOut,
    ConsentIn,
    ConsentOut,
    DeviceHeartbeatIn,
    DeviceOut,
    DeviceRegisterIn,
    EventResultOut,
    LocationBatchIn,
    LocationEventIn,
    LocationHistoryOut,
    MyLocationStatus,
    OfficeFence,
    TrackingWindow,
    UncertainEventOut,
)
from app.services import attendance_service as att
from app.services import location_service as loc
from app.services.anomalies import raise_anomaly
from app.services.audit import audit
from app.services.notifications import notify_hr
from app.services.schedule_service import next_shift

router = APIRouter(tags=["locations"])

CONSENT_VERSION = "1.0"
CONSENT_TEXT = (
    "Your employer uses your device location ONLY to record attendance at assigned office locations. "
    "Location is collected only during your scheduled working window (plus a short configurable margin before and after), "
    "and a visible indicator is shown while tracking is active. Administrators see your attendance status, distance to the office "
    "and GPS accuracy - never a movement trail. Raw coordinates are deleted automatically after the retention period. "
    "You can withdraw consent at any time in Location Settings; attendance will then need to be recorded manually."
)


def _http_for(result: loc.EventResult) -> int:
    if result.result == "REJECTED":
        return status.HTTP_403_FORBIDDEN if result.reason in loc.PERMISSION_REJECTS else status.HTTP_422_UNPROCESSABLE_ENTITY
    if result.result == "DUPLICATE":
        return status.HTTP_200_OK
    return status.HTTP_201_CREATED


@router.post("/locations/events/", response_model=EventResultOut, status_code=201)
def post_event(body: LocationEventIn, response: Response, p: Principal = Depends(location_rate_limit), db: Session = Depends(get_db)):
    if p.employee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    [res] = loc.ingest(db, p.employee.id, [body], utcnow())
    code = _http_for(res)
    if code >= 400:
        raise HTTPException(code, {"code": res.reason, "client_event_id": res.client_event_id})
    response.status_code = code
    return EventResultOut(**res.as_dict())


@router.post("/locations/batch/", response_model=BatchResultOut)
def post_batch(body: LocationBatchIn, p: Principal = Depends(location_rate_limit), db: Session = Depends(get_db)):
    """Offline sync. Each item is validated & processed independently; one bad item never blocks the queue."""
    if p.employee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    valid: list[LocationEventIn] = []
    invalid: list[EventResultOut] = []
    for raw in body.events:
        try:
            valid.append(LocationEventIn.model_validate(raw))
        except ValidationError as exc:
            invalid.append(EventResultOut(client_event_id=str(raw.get("client_event_id")) if isinstance(raw, dict) and raw.get("client_event_id") else None,
                                          result="REJECTED", reason="VALIDATION_ERROR",
                                          errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]))
    results = [EventResultOut(**r.as_dict()) for r in loc.ingest(db, p.employee.id, valid, utcnow())] + invalid
    return BatchResultOut(results=results, accepted=sum(r.result not in ("REJECTED", "DUPLICATE") for r in results),
                          duplicates=sum(r.result == "DUPLICATE" for r in results), rejected=sum(r.result == "REJECTED" for r in results))


@router.get("/locations/me/status/", response_model=MyLocationStatus)
def my_status(p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    emp = p.employee
    now = utcnow()
    settings = att.org_settings(db, p.org_id)
    consent = loc.current_consent(db, emp.id)
    dev = db.scalar(select(DeviceRegistration).where(DeviceRegistration.employee_id == emp.id, DeviceRegistration.is_active.is_(True))
                    .order_by(DeviceRegistration.last_seen_at.desc().nulls_last()).limit(1))
    shift = next_shift(db, emp, now, settings)
    window = None
    if shift:
        window = TrackingWindow(work_date=shift.work_date, start=shift.window_start, end=shift.window_end, shift_start=shift.start, shift_end=shift.end,
                                active=shift.in_window(now))
    consent_ok = bool(consent and consent.granted)
    offices = [OfficeFence(id=o.id, name=o.name, latitude=o.latitude, longitude=o.longitude, radius_m=o.geofence.radius_m,
                           max_accuracy_m=o.geofence.max_accuracy_m, timezone=o.timezone) for o in loc.candidate_offices(db, emp)]
    live = loc.live_status(db, emp)
    db.commit()
    return MyLocationStatus(
        employee_id=emp.id, employee_name=emp.full_name, consent_granted=consent_ok, consent_version_required=CONSENT_VERSION,
        device_registered=dev is not None, location_permission=dev.location_permission.value if dev else None,
        tracking_active=bool(consent_ok and window and window.active), tracking_window=window, offices=offices,
        presence=live["presence"], office_id=live["office_id"], last_zone=live["last_zone"], distance_m=live["distance_m"],
        accuracy_m=live["accuracy_m"], last_update=live["last_update"], session_status=live["session_status"], server_time=now,
    )


@router.get("/locations/me/history/", response_model=Page[LocationHistoryOut])
def my_history(pg: tuple[int, int] = Depends(pagination), p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    page, size = pg
    q = select(LocationEvent).where(LocationEvent.employee_id == p.employee.id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.order_by(LocationEvent.recorded_at.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[LocationHistoryOut.model_validate(i) for i in items], total=total or 0, page=page, page_size=size)


@router.get("/locations/monitoring/")
def monitoring(office_id: int | None = None, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """Deprecated alias of GET /monitoring/employees/ (same rows; no coordinates or trails)."""
    from app.api.v1.endpoints.monitoring import build_rows

    return build_rows(db, p, office_id)


@router.get("/locations/uncertain/", response_model=list[UncertainEventOut])
def uncertain_events(hours: int = 24, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(hours=min(max(hours, 1), 168))
    q = scope_employees(select(LocationEvent, Employee.full_name).join(Employee, Employee.id == LocationEvent.employee_id), p).where(
        LocationEvent.received_at >= since,
        (LocationEvent.zone == Zone.UNCERTAIN) | LocationEvent.processing_status.in_([EventProcessingStatus.LOW_ACCURACY, EventProcessingStatus.SUSPICIOUS]),
    ).order_by(LocationEvent.recorded_at.desc()).limit(500)
    return [UncertainEventOut(id=ev.id, employee_id=ev.employee_id, employee_name=name, office_id=ev.office_id,
                              distance_m=round(ev.distance_m, 1) if ev.distance_m is not None else None, accuracy_m=ev.accuracy_m,
                              recorded_at=ev.recorded_at, processing_status=ev.processing_status.value, status_reason=ev.status_reason)
            for ev, name in db.execute(q).all()]


# ----------------------------------------------------------------- devices ----

@router.post("/devices/register/", response_model=DeviceOut)
def register_device(body: DeviceRegisterIn, request: Request, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    rate_limit.check(f"dev:{p.user.id}", "30/60")
    emp = p.employee
    dev = db.scalar(select(DeviceRegistration).where(DeviceRegistration.employee_id == emp.id, DeviceRegistration.device_id == body.device_id))
    other = db.scalar(select(DeviceRegistration).where(DeviceRegistration.organization_id == p.org_id, DeviceRegistration.device_id == body.device_id,
                                                       DeviceRegistration.employee_id != emp.id, DeviceRegistration.is_active.is_(True)))
    if other is not None:
        raise_anomaly(db, org_id=p.org_id, employee_id=emp.id, type=AnomalyType.SHARED_DEVICE, severity=AnomalySeverity.HIGH,
                      work_date=utcnow().date(), details={"device_id": body.device_id, "registered_to_employee_id": other.employee_id})
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is registered to another employee. Contact HR.")
    created = dev is None
    if dev is None:
        dev = DeviceRegistration(organization_id=p.org_id, employee_id=emp.id, device_id=body.device_id, platform=body.platform)
        db.add(dev)
    if dev.location_permission != body.location_permission or dev.permission_updated_at is None:
        dev.permission_updated_at = utcnow()
    for k, v in body.model_dump().items():
        setattr(dev, k, v)
    dev.is_active, dev.last_seen_at = True, utcnow()
    db.flush()
    if created:
        audit(db, org_id=p.org_id, actor_id=p.user.id, action="device.registered", entity_type="device", entity_id=dev.id,
              changes={"platform": body.platform, "model": body.model}, ip=rate_limit.client_ip(request))
    db.commit()
    return dev


@router.post("/devices/heartbeat/", response_model=DeviceOut)
def heartbeat(body: DeviceHeartbeatIn, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    """Periodic permission/status report. Revocation is recorded as an informational anomaly, never as absence."""
    rate_limit.check(f"hb:{p.user.id}", "60/60")
    dev = db.scalar(select(DeviceRegistration).where(DeviceRegistration.employee_id == p.employee.id, DeviceRegistration.device_id == body.device_id,
                                                     DeviceRegistration.is_active.is_(True)))
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not registered")
    was_granted = dev.location_permission in (PermissionStatus.GRANTED_ALWAYS, PermissionStatus.GRANTED_WHEN_IN_USE)
    now_denied = body.location_permission in (PermissionStatus.DENIED, PermissionStatus.RESTRICTED)
    if was_granted and now_denied:
        raise_anomaly(db, org_id=p.org_id, employee_id=p.employee.id, type=AnomalyType.PERMISSION_REVOKED, severity=AnomalySeverity.INFO,
                      details={"device_id": dev.device_id, "permission": body.location_permission.value})
        audit(db, org_id=p.org_id, actor_id=p.user.id, action="device.permission_revoked", entity_type="device", entity_id=dev.id)
    if dev.location_permission != body.location_permission:
        dev.permission_updated_at = utcnow()
    dev.location_permission, dev.precise_location, dev.background_enabled = body.location_permission, body.precise_location, body.background_enabled
    if body.push_token:
        dev.push_token = body.push_token
    dev.last_seen_at = utcnow()
    db.commit()
    return dev


@router.get("/devices/me/", response_model=list[DeviceOut])
def my_devices(p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    return db.scalars(select(DeviceRegistration).where(DeviceRegistration.employee_id == p.employee.id).order_by(DeviceRegistration.created_at.desc())).all()


@router.delete("/devices/{device_pk}/", status_code=204)
def deactivate_device(device_pk: int, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    dev = db.get(DeviceRegistration, device_pk)
    if dev is None or dev.employee_id != p.employee.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    dev.is_active, dev.push_token = False, None
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="device.deactivated", entity_type="device", entity_id=dev.id)
    db.commit()


# ----------------------------------------------------------------- consent ----

@router.get("/consent/me/", response_model=ConsentOut)
def my_consent(p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    c = loc.current_consent(db, p.employee.id)
    return ConsentOut(granted=bool(c and c.granted and c.consent_version == CONSENT_VERSION), consent_version=c.consent_version if c else None,
                      updated_at=c.created_at if c else None, required_version=CONSENT_VERSION, policy_text=CONSENT_TEXT)


@router.post("/consent/", response_model=ConsentOut, status_code=201)
def set_consent(body: ConsentIn, request: Request, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    if body.granted and body.consent_version != CONSENT_VERSION:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Please review and accept consent version {CONSENT_VERSION}")
    c = LocationConsent(organization_id=p.org_id, employee_id=p.employee.id, granted=body.granted, consent_version=body.consent_version,
                        ip_address=rate_limit.client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300], created_at=utcnow())
    db.add(c)
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="consent.granted" if body.granted else "consent.withdrawn", entity_type="location_consent",
          entity_id=p.employee.id, changes={"version": body.consent_version})
    if not body.granted:
        notify_hr(db, p.org_id, p.employee.department_id, type="CONSENT_WITHDRAWN", title="Location consent withdrawn",
                  body=f"{p.employee.full_name} withdrew location consent. Attendance must be recorded manually.", data={"employee_id": p.employee.id})
    db.commit()
    return ConsentOut(granted=body.granted, consent_version=body.consent_version, updated_at=c.created_at, required_version=CONSENT_VERSION, policy_text=CONSENT_TEXT)
