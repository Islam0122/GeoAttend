"""Employee Monitoring for Manager / HR / Admin.

Reads only the latest server-validated presence (no GPS is requested from the manager's browser) and never
exposes coordinates, trails or history. Managers see only employees in their departments (RBAC scoping).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require_staff, scope_employees
from app.core.db import get_db
from app.core.timeutils import utcnow
from app.models import Employee, Office
from app.services import attendance_service as att
from app.services import presence_service

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

FILTERS = {
    "all": lambda r: True,
    "inside": lambda r: r.zone_status == "INSIDE",
    "outside": lambda r: r.zone_status == "OUTSIDE",
    "active": lambda r: r.session_status == "ACTIVE",
    "late": lambda r: r.late_minutes > 0,
    "temporary_exit": lambda r: r.session_status == "TEMPORARY_EXIT",
    "stale": lambda r: r.zone_status == "STALE",
    "no_permission": lambda r: r.zone_status == "LOCATION_DENIED" or not r.consent_granted,
    "no_office": lambda r: r.zone_status == "NO_OFFICE",
}


class MonitoringEmployee(BaseModel):
    employee_id: int
    employee_name: str
    position: str | None
    department_name: str | None
    assigned_offices: list[str]
    office_id: int | None
    office_name: str | None
    zone_status: str            # INSIDE OUTSIDE LOCATION_DETECTED STALE UNKNOWN LOCATION_DENIED NO_OFFICE
    zone_reason: str
    distance_m: float | None
    accuracy_m: float | None
    last_update: datetime | None
    last_activity: datetime | None
    permission: str | None
    consent_granted: bool
    attendance_status: str      # PRESENT LATE UNSCHEDULED ... NOT_CHECKED_IN NO_SHIFT
    session_status: str         # ACTIVE TEMPORARY_EXIT PENDING_CHECKOUT COMPLETED NOT_STARTED
    check_in_time: datetime | None
    check_out_time: datetime | None
    working_minutes: int
    late_minutes: int
    temporary_exit_started_at: datetime | None
    temporary_exit_minutes: int


class MonitoringSummary(BaseModel):
    generated_at: datetime
    total_employees: int
    currently_inside: int
    currently_outside: int
    active_sessions: int
    late_today: int
    temporary_exits: int
    location_unavailable: int   # STALE + UNKNOWN + LOCATION_DENIED
    stale: int
    no_permission: int
    no_office: int
    stale_after_seconds: int


def build_rows(db: Session, p: Principal, office_id: int | None = None) -> list[MonitoringEmployee]:
    now = utcnow()
    settings = att.org_settings(db, p.org_id)
    offices = dict(db.execute(select(Office.id, Office.name).where(Office.organization_id == p.org_id)).all())
    emps = db.scalars(scope_employees(select(Employee), p).where(Employee.is_active.is_(True)).order_by(Employee.full_name)).unique().all()
    rows = []
    for e in emps:
        v = presence_service.resolve(db, e, now, settings=settings, recompute_live=True)
        if office_id and office_id not in v.assigned_office_ids:
            continue
        rows.append(MonitoringEmployee(
            employee_id=e.id, employee_name=e.full_name, position=e.position, department_name=e.department.name if e.department else None,
            assigned_offices=[offices[i] for i in v.assigned_office_ids if i in offices], office_id=v.office_id,
            office_name=offices.get(v.office_id) if v.office_id else None, zone_status=v.zone_status, zone_reason=v.reason,
            distance_m=v.distance_m, accuracy_m=v.accuracy_m, last_update=v.last_update, last_activity=v.last_activity,
            permission=v.permission, consent_granted=v.consent_granted, attendance_status=v.attendance_status, session_status=v.session_status,
            check_in_time=v.check_in_time, check_out_time=v.check_out_time, working_minutes=v.working_minutes, late_minutes=v.late_minutes,
            temporary_exit_started_at=v.temporary_exit_started_at, temporary_exit_minutes=v.temporary_exit_minutes,
        ))
    db.commit()  # persists live working-time recomputation
    return rows


@router.get("/employees/", response_model=list[MonitoringEmployee])
def employees(filter: str = "all", office_id: int | None = None, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    if filter not in FILTERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"filter must be one of {sorted(FILTERS)}")
    return [r for r in build_rows(db, p, office_id) if FILTERS[filter](r)]


@router.get("/summary/", response_model=MonitoringSummary)
def summary(office_id: int | None = None, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    rows = build_rows(db, p, office_id)
    count = lambda f: sum(1 for r in rows if FILTERS[f](r))  # noqa: E731
    return MonitoringSummary(
        generated_at=utcnow(), total_employees=len(rows), currently_inside=count("inside"), currently_outside=count("outside"),
        active_sessions=count("active"), late_today=count("late"), temporary_exits=count("temporary_exit"),
        location_unavailable=sum(1 for r in rows if r.zone_status in ("STALE", "UNKNOWN", "LOCATION_DENIED")), stale=count("stale"),
        no_permission=count("no_permission"), no_office=count("no_office"),
        stale_after_seconds=att.org_settings(db, p.org_id).presence_stale_seconds,
    )
