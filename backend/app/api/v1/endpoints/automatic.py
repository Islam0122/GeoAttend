"""Automatic attendance API: presence checks, automatic status, sessions, policy and admin overrides."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    get_employee_or_404,
    get_principal,
    location_rate_limit,
    pagination,
    require_admin,
    require_employee,
    scope_employees,
)
from app.core.db import get_db
from app.core.timeutils import ensure_utc, utcnow
from app.models import AttendanceRecord, AttendanceSession, Employee, GeofenceTransition, Office, OfficeAssignment
from app.models.enums import EventTrigger, PermissionStatus, Platform, Role, SessionStatus
from app.permissions.rbac import HR_ROLES
from app.schemas.common import Page
from app.schemas.location import LocationEventIn
from app.schemas.org import SettingsOut, SettingsPatch
from app.services import attendance_service as att
from app.services import automatic_status
from app.services import location_service as loc
from app.services import presence_service
from app.services.audit import audit, diff

router = APIRouter(tags=["automatic attendance"])

POLICY_FIELDS = [
    "attendance_mode", "automatic_detection_enabled", "automatic_checkin_enabled", "automatic_checkout_enabled", "automatic_resume_enabled",
    "presence_interval_seconds", "default_max_accuracy_m", "entry_confirmation_count", "exit_confirmation_count", "presence_stale_seconds",
    "temporary_exit_grace_minutes", "temporary_exit_max_minutes", "checkout_grace_minutes", "automatic_checkout_timeout_minutes",
    "allow_unscheduled_attendance", "require_registered_device", "count_temporary_exit_as_work", "confirmation_policy",
]


class PresenceCheckIn(BaseModel):
    """One browser GPS fix. Zone, distance and attendance are always computed by the server."""

    event_uuid: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-:.]+$")
    device_id: str = Field(min_length=4, max_length=128)
    latitude: float
    longitude: float
    accuracy: float
    timestamp: datetime
    permission_status: str = "GRANTED_WHEN_IN_USE"
    source: str = Field(default="watch", max_length=16)  # watch | current (diagnostics only)


def _policy(s) -> dict:
    return {k: (getattr(s, k).value if hasattr(getattr(s, k), "value") else getattr(s, k)) for k in POLICY_FIELDS} | {
        "automatic_attendance": s.automatic_attendance, "manual_actions_allowed": s.manual_actions_allowed}


def _office_info(db: Session, office_id: int | None) -> dict | None:
    o = db.get(Office, office_id) if office_id else None
    return {"id": o.id, "name": o.name, "radius_m": o.geofence.radius_m, "max_accuracy_m": o.geofence.max_accuracy_m} if o else None


def _status_payload(db: Session, emp: Employee, now: datetime, *, reading: dict | None = None) -> dict:
    settings = att.org_settings(db, emp.organization_id)
    view = presence_service.resolve(db, emp, now, settings=settings, recompute_live=True)
    state, message = automatic_status.derive(view, settings, effects=(reading or {}).get("effects"), reading=reading)
    return {"ui_state": state, "message": message, "server_time": now, "policy": _policy(settings), "presence": view.as_dict(),
            "office": _office_info(db, (reading or {}).get("office_id") or view.office_id or emp.primary_office_id), "reading": reading}


@router.post("/attendance/presence-check/")
def presence_check(body: PresenceCheckIn, p: Principal = Depends(location_rate_limit), db: Session = Depends(get_db)):
    """Submit one GPS fix from the open Attendance screen. Idempotent per event_uuid."""
    if p.employee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    now = utcnow()
    settings = att.org_settings(db, p.org_id)
    recorded = ensure_utc(body.timestamp)
    if now - recorded > timedelta(seconds=settings.presence_stale_seconds):
        # A delayed measurement is never replayed as the current position.
        reading = {"result": "REJECTED", "reason": "STALE_MEASUREMENT", "client_event_id": body.event_uuid}
        return _status_payload(db, p.employee, now, reading=reading)
    try:
        perm = PermissionStatus(body.permission_status)
    except ValueError:
        perm = PermissionStatus.UNKNOWN
    item = LocationEventIn(client_event_id=body.event_uuid, device_id=body.device_id, latitude=body.latitude, longitude=body.longitude,
                           accuracy=body.accuracy, recorded_at=recorded, platform=Platform.WEB, permission_status=perm, trigger=EventTrigger.FOREGROUND)
    [res] = loc.ingest(db, p.employee.id, [item], now)
    if res.result == "REJECTED":
        if res.reason in loc.PERMISSION_REJECTS:
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": res.reason})
        if res.reason == loc.RejectReason.DETECTION_DISABLED:
            raise HTTPException(status.HTTP_409_CONFLICT, {"code": res.reason, "message": "Automatic presence detection is disabled."})
        if res.reason not in (loc.RejectReason.OUTSIDE_TRACKING_WINDOW,):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": res.reason})
    db.expire_all()
    emp = db.get(Employee, p.employee.id)
    payload = _status_payload(db, emp, now, reading=res.as_dict())
    db.commit()
    return payload


@router.get("/attendance/automatic/status/")
def automatic_status_view(p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    """Current server-side state (no GPS needed) — used on page load and while offline recovery happens."""
    payload = _status_payload(db, p.employee, utcnow())
    db.commit()
    return payload


@router.get("/attendance/automatic/today/")
def automatic_today(p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    """Today's sessions, temporary exits and the presence-event timeline (no coordinates)."""
    now = utcnow()
    payload = _status_payload(db, p.employee, now)
    rid = payload["presence"]["record_id"]
    rec = db.get(AttendanceRecord, rid) if rid else None
    events = []
    if rec is not None:
        start = (rec.scheduled_start or datetime.combine(rec.work_date, datetime.min.time())) - timedelta(hours=12)
        for tr in db.scalars(select(GeofenceTransition).where(GeofenceTransition.employee_id == p.employee.id, GeofenceTransition.occurred_at >= start)
                             .order_by(GeofenceTransition.occurred_at)).all():
            events.append({"type": tr.type.value, "effect": tr.attendance_effect, "office_id": tr.office_id, "occurred_at": tr.occurred_at,
                           "confirmed_at": tr.confirmed_at, "readings": tr.readings, "note": tr.note})
    payload["record"] = _record_dict(rec) if rec else None
    payload["events"] = events
    db.commit()
    return payload


def _record_dict(r: AttendanceRecord) -> dict:
    keys = ["id", "employee_id", "work_date", "timezone", "scheduled_start", "scheduled_end", "actual_check_in", "actual_check_out", "late_minutes",
            "early_arrival_minutes", "early_departure_minutes", "worked_minutes", "presence_minutes", "temporary_exit_minutes", "break_minutes",
            "overtime_minutes", "is_unscheduled", "is_finalized", "is_confirmed"]
    d = {k: getattr(r, k) for k in keys}
    d["status"] = r.status.value
    d["payable_minutes"] = r.worked_minutes
    d["sessions"] = [_session_dict(s) for s in r.sessions]
    return d


def _session_dict(s: AttendanceSession) -> dict:
    return {
        "id": s.id, "employee_id": s.employee_id, "office_id": s.office_id, "record_id": s.record_id, "status": s.status.value,
        "detection_method": s.detection_method, "confirmation": s.confirmation.value, "started_at": s.check_in_at, "ended_at": s.check_out_at,
        "close_reason": s.close_reason.value if s.close_reason else None, "check_in_accuracy_m": s.check_in_accuracy_m,
        "check_in_device_id": s.check_in_device_id, "total_minutes": s.gross_minutes, "payable_minutes": s.duration_minutes,
        "temporary_exits": [{
            "id": b.id, "type": b.type.value, "exited_at": b.started_at,
            "returned_at": b.ended_at if b.outcome == "RETURNED" else None, "outcome": b.outcome, "duration_minutes": b.duration_minutes,
            "counted_as_working_time": b.is_paid, "detection_method": b.detection_method} for b in s.breaks],
    }


@router.get("/attendance/sessions/")
def list_sessions(date_from: date | None = None, date_to: date | None = None, employee_id: int | None = None,
                  pg: tuple[int, int] = Depends(pagination), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    page, size = pg
    q = scope_employees(select(AttendanceSession).join(AttendanceRecord, AttendanceRecord.id == AttendanceSession.record_id)
                        .join(Employee, Employee.id == AttendanceSession.employee_id), p).where(AttendanceSession.organization_id == p.org_id)
    if date_from:
        q = q.where(AttendanceRecord.work_date >= date_from)
    if date_to:
        q = q.where(AttendanceRecord.work_date <= date_to)
    if employee_id:
        q = q.where(AttendanceSession.employee_id == employee_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = db.scalars(q.order_by(AttendanceSession.check_in_at.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_session_dict(s) for s in items], total=total, page=page, page_size=size)


class SessionOverride(BaseModel):
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    office_id: int | None = None
    reason: str = Field(min_length=3, max_length=2000)


@router.patch("/attendance/sessions/{session_id}/")
def override_session(session_id: int, body: SessionOverride, request: Request, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Admin/HR manual override (also in Automatic mode). Managers file correction requests instead."""
    if p.role not in HR_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators or HR can edit attendance directly; please request a correction")
    s = db.get(AttendanceSession, session_id)
    if s is None or s.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    emp = get_employee_or_404(db, p, s.employee_id)
    if p.employee is not None and emp.id == p.employee.id and p.role != Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot edit your own attendance")
    loc.lock_employee(db, emp.id)
    if body.office_id is not None:
        if not db.scalar(select(OfficeAssignment.id).where(OfficeAssignment.employee_id == emp.id, OfficeAssignment.office_id == body.office_id)) \
                and emp.primary_office_id != body.office_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Office is not assigned to this employee")
    new_in = ensure_utc(body.check_in_at) if body.check_in_at else s.check_in_at
    new_out = ensure_utc(body.check_out_at) if body.check_out_at else s.check_out_at
    if new_out is not None and new_out <= new_in:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Check-out must be after check-in")
    now = utcnow()
    changes = diff(s, {k: v for k, v in {"check_in_at": new_in, "office_id": body.office_id}.items() if v is not None})
    if body.check_out_at is not None:
        if s.status in (SessionStatus.OPEN, SessionStatus.AWAY):
            from app.models.enums import CloseReason

            att.close_session(db, s, new_out, CloseReason.CORRECTION, att.org_settings(db, p.org_id), now)
        changes.update(diff(s, {"check_out_at": new_out}))
        s.status, s.checkout_confirmed_at = SessionStatus.CLOSED, now
    s.detection_method = "CORRECTION" if changes else s.detection_method
    att.recompute(db, s.record, now)
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="attendance.session_override", entity_type="attendance_session", entity_id=s.id,
          changes={"changes": changes, "reason": body.reason}, ip=request.client.host if request.client else None)
    db.commit()
    return _session_dict(s)


@router.get("/attendance/policy/")
def get_policy(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = att.org_settings(db, p.org_id)
    db.commit()
    return _policy(s)


@router.patch("/attendance/policy/", response_model=SettingsOut)
def patch_policy(body: SettingsPatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    s = att.org_settings(db, p.org_id)
    changes = diff(s, body.model_dump(exclude_unset=True, exclude_none=True))
    if changes:
        audit(db, org_id=p.org_id, actor_id=p.user.id, action="policy.updated", entity_type="organization_settings", entity_id=p.org_id, changes=changes)
    db.commit()
    return s
