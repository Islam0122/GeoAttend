from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require_admin
from app.core.db import get_db
from app.models import Employee, Office, OfficeAssignment, OfficeGeofence, Organization
from app.models.enums import Role
from app.schemas.office import (
    GeofenceOut,
    GeofencePatch,
    OfficeCreate,
    OfficeOut,
    OfficePatch,
)
from app.services import attendance_service as att
from app.services import plans
from app.services.audit import audit, diff

router = APIRouter(prefix="/offices", tags=["offices"])


def _out(db: Session, o: Office) -> OfficeOut:
    ids = sorted(db.scalars(select(OfficeAssignment.employee_id).where(OfficeAssignment.office_id == o.id)).all())
    return OfficeOut(id=o.id, name=o.name, address=o.address, latitude=o.latitude, longitude=o.longitude, timezone=o.timezone,
                     is_active=o.is_active, radius=o.geofence.radius_m, max_accuracy=o.geofence.max_accuracy_m, geofence=GeofenceOut.model_validate(o.geofence), employee_ids=ids, created_at=o.created_at)


def _get(db: Session, p: Principal, office_id: int) -> Office:
    o = db.get(Office, office_id)
    if o is None or o.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Office not found")
    return o


def _assign(db: Session, p: Principal, office: Office, employee_ids: list[int]) -> None:
    ids = set(employee_ids)
    if ids:
        n = db.scalar(select(func.count()).select_from(Employee).where(Employee.id.in_(ids), Employee.organization_id == p.org_id))
        if n != len(ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown employee")
    db.execute(delete(OfficeAssignment).where(OfficeAssignment.office_id == office.id))
    for eid in sorted(ids):
        db.add(OfficeAssignment(organization_id=p.org_id, office_id=office.id, employee_id=eid))


@router.get("/", response_model=list[OfficeOut])
def list_offices(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(Office).where(Office.organization_id == p.org_id).order_by(Office.name)
    if p.role == Role.EMPLOYEE:
        q = q.where(Office.is_active.is_(True))
    return [_out(db, o) for o in db.scalars(q).unique().all()]


@router.post("/", response_model=OfficeOut, status_code=201)
def create_office(body: OfficeCreate, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    plans.enforce(db, p.org_id, "offices")
    s = att.org_settings(db, p.org_id)
    org = db.get(Organization, p.org_id)
    office = Office(organization_id=p.org_id, name=body.name, address=body.address, latitude=body.latitude, longitude=body.longitude,
                    timezone=body.timezone or org.timezone, is_active=body.is_active)
    fence = OfficeGeofence(organization_id=p.org_id, radius_m=s.default_radius_m, max_accuracy_m=s.default_max_accuracy_m,
                           required_consecutive=s.required_consecutive, stability_window_seconds=s.stability_window_seconds,
                           entry_buffer_m=s.entry_buffer_m, exit_buffer_m=s.exit_buffer_m)
    if body.geofence:
        for k, v in body.geofence.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(fence, k, v)
    if body.radius is not None:
        fence.radius_m = body.radius
    if body.max_accuracy is not None:
        fence.max_accuracy_m = body.max_accuracy
    office.geofence = fence
    db.add(office)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An office with this name already exists") from None
    _assign(db, p, office, body.employee_ids)
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="office.created", entity_type="office", entity_id=office.id,
          changes={"name": office.name, "lat": office.latitude, "lng": office.longitude, "radius_m": fence.radius_m})
    db.commit()
    return _out(db, office)


@router.get("/{office_id}/", response_model=OfficeOut)
def get_office(office_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _out(db, _get(db, p, office_id))


@router.patch("/{office_id}/", response_model=OfficeOut)
def patch_office(office_id: int, body: OfficePatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    office = _get(db, p, office_id)
    data = body.model_dump(exclude_unset=True)
    emp_ids = data.pop("employee_ids", None)
    fence_changes = diff(office.geofence, {k: v for k, v in {"radius_m": data.pop("radius", None), "max_accuracy_m": data.pop("max_accuracy", None)}.items() if v is not None})
    if data.get("is_active") is True and not office.is_active:
        plans.enforce(db, p.org_id, "offices")
    changes = diff(office, {k: v for k, v in data.items() if v is not None or k == "address"})
    changes.update(fence_changes)
    if emp_ids is not None:
        _assign(db, p, office, emp_ids)
        changes["employee_ids"] = emp_ids
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="office.updated", entity_type="office", entity_id=office.id, changes=changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An office with this name already exists") from None
    return _out(db, office)


@router.get("/{office_id}/geofence/", response_model=GeofenceOut)
def get_geofence(office_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _get(db, p, office_id).geofence


@router.patch("/{office_id}/geofence/", response_model=GeofenceOut)
def patch_geofence(office_id: int, body: GeofencePatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    office = _get(db, p, office_id)
    changes = diff(office.geofence, body.model_dump(exclude_unset=True, exclude_none=True))
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="geofence.updated", entity_type="office_geofence", entity_id=office.id, changes=changes)
    db.commit()
    return office.geofence


@router.delete("/{office_id}/", status_code=204)
def delete_office(office_id: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Deactivates the office and its geofence (history references it, so the row is kept)."""
    office = _get(db, p, office_id)
    office.is_active = False
    office.geofence.enabled = False
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="office.deactivated", entity_type="office", entity_id=office.id)
    db.commit()
