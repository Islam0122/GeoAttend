from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    get_employee_or_404,
    pagination,
    require_hr,
    require_staff,
    scope_employees,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import new_invite_token
from app.core.timeutils import utcnow
from app.models import (
    Department,
    DeviceRegistration,
    Employee,
    ManagerDepartment,
    Office,
    OfficeAssignment,
    User,
)
from app.models.enums import EmploymentStatus, Role
from app.schemas.common import Page
from app.schemas.org import EmployeeCreate, EmployeeCreated, EmployeeOut, EmployeePatch
from app.services import plans
from app.services.audit import audit, diff
from app.services.location_service import current_consent
from app.services.notifications import send_email

router = APIRouter(prefix="/employees", tags=["employees"])


def serialize_employee(db: Session, e: Employee) -> EmployeeOut:
    consent = current_consent(db, e.id)
    dev = db.scalar(select(DeviceRegistration).where(DeviceRegistration.employee_id == e.id, DeviceRegistration.is_active.is_(True))
                    .order_by(DeviceRegistration.last_seen_at.desc().nulls_last()).limit(1))
    return EmployeeOut(
        id=e.id, user_id=e.user_id, full_name=e.full_name, email=e.user.email, employee_code=e.employee_code, position=e.position,
        employment_status=e.employment_status, hired_at=e.hired_at,
        department_id=e.department_id, department_name=e.department.name if e.department else None, primary_office_id=e.primary_office_id,
        office_ids=sorted(db.scalars(select(OfficeAssignment.office_id).where(OfficeAssignment.employee_id == e.id)).all()),
        role=e.user.role, managed_department_ids=sorted(d.id for d in e.user.managed_departments), is_active=e.is_active,
        invite_pending=e.user.invite_token_hash is not None, consent_granted=consent.granted if consent else None,
        location_permission=dev.location_permission.value if dev else None, created_at=e.created_at,
    )


def _check_refs(db: Session, org_id: int, department_id: int | None, office_ids: list[int], dept_ids: list[int]) -> None:
    if department_id is not None:
        d = db.get(Department, department_id)
        if d is None or d.organization_id != org_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown department")
    if office_ids:
        n = db.scalar(select(func.count()).select_from(Office).where(Office.id.in_(office_ids), Office.organization_id == org_id))
        if n != len(set(office_ids)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown office")
    if dept_ids:
        n = db.scalar(select(func.count()).select_from(Department).where(Department.id.in_(dept_ids), Department.organization_id == org_id))
        if n != len(set(dept_ids)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown managed department")


def _set_offices(db: Session, org_id: int, emp_id: int, office_ids: list[int]) -> None:
    db.execute(delete(OfficeAssignment).where(OfficeAssignment.employee_id == emp_id))
    for oid in sorted(set(office_ids)):
        db.add(OfficeAssignment(organization_id=org_id, office_id=oid, employee_id=emp_id))


def _set_managed(db: Session, org_id: int, user: User, dept_ids: list[int]) -> None:
    db.execute(delete(ManagerDepartment).where(ManagerDepartment.user_id == user.id))
    for did in sorted(set(dept_ids)):
        db.add(ManagerDepartment(organization_id=org_id, user_id=user.id, department_id=did))
    db.flush()
    db.expire(user, ["managed_departments"])


@router.get("/", response_model=Page[EmployeeOut])
def list_employees(q: str | None = None, department_id: int | None = None, office_id: int | None = None, active: bool | None = None,
                   pg: tuple[int, int] = Depends(pagination), p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    page, size = pg
    stmt = scope_employees(select(Employee), p)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Employee.full_name).like(like) | func.lower(Employee.employee_code).like(like))
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if office_id:
        stmt = stmt.where(Employee.id.in_(select(OfficeAssignment.employee_id).where(OfficeAssignment.office_id == office_id)))
    if active is not None:
        stmt = stmt.where(Employee.is_active.is_(active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Employee.full_name).offset((page - 1) * size).limit(size)).unique().all()
    return Page(items=[serialize_employee(db, e) for e in rows], total=total or 0, page=page, page_size=size)


@router.post("/", response_model=EmployeeCreated, status_code=201)
def create_employee(body: EmployeeCreate, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    if body.role == Role.ADMIN and p.role not in (Role.OWNER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can create admins")
    plans.enforce(db, p.org_id, "employees")
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if db.scalar(select(Employee.id).where(Employee.organization_id == p.org_id, Employee.employee_code == body.employee_code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee code already in use")
    office_ids = list(body.office_ids) + ([body.primary_office_id] if body.primary_office_id else [])
    _check_refs(db, p.org_id, body.department_id, office_ids, body.managed_department_ids)
    raw, hashed = new_invite_token()
    user = User(organization_id=p.org_id, email=body.email.lower(), full_name=body.full_name, role=body.role,
                invite_token_hash=hashed, invite_expires_at=utcnow() + timedelta(hours=get_settings().invite_token_hours))
    db.add(user)
    db.flush()
    emp = Employee(organization_id=p.org_id, user_id=user.id, full_name=body.full_name, employee_code=body.employee_code, position=body.position,
                   department_id=body.department_id, primary_office_id=body.primary_office_id,
                   employment_status=body.employment_status, hired_at=body.hired_at)
    db.add(emp)
    db.flush()
    _set_offices(db, p.org_id, emp.id, office_ids)
    if body.role == Role.MANAGER:
        _set_managed(db, p.org_id, user, body.managed_department_ids)
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="employee.invited", entity_type="employee", entity_id=emp.id,
          changes={"email": user.email, "role": body.role, "office_ids": office_ids})
    db.commit()
    db.refresh(emp)
    invite_url = f"{get_settings().frontend_url}/accept-invite?token={raw}"
    send_email(user.email, "You're invited to GeoAttend", f"Hello {emp.full_name},\n\nSet your password to join: {invite_url}\n")
    return EmployeeCreated(**serialize_employee(db, emp).model_dump(), invite_url=invite_url)


@router.get("/{employee_id}/", response_model=EmployeeOut)
def get_employee(employee_id: int, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return serialize_employee(db, get_employee_or_404(db, p, employee_id))


@router.patch("/{employee_id}/", response_model=EmployeeOut)
def patch_employee(employee_id: int, body: EmployeePatch, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    emp = get_employee_or_404(db, p, employee_id)
    data = body.model_dump(exclude_unset=True)
    if emp.user.role == Role.OWNER and (data.get("role") not in (None, Role.OWNER) or data.get("is_active") is False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The owner account cannot be demoted or deactivated")
    if data.get("role") == Role.OWNER:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "OWNER role cannot be assigned")
    if data.get("role") == Role.ADMIN and p.role not in (Role.OWNER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can grant admin")
    _check_refs(db, p.org_id, data.get("department_id"), (data.get("office_ids") or []) + ([data["primary_office_id"]] if data.get("primary_office_id") else []),
                data.get("managed_department_ids") or [])
    if data.get("is_active") is True and not emp.is_active:
        plans.enforce(db, p.org_id, "employees")
    changes = diff(emp, {k: v for k, v in data.items() if k in ("full_name", "position", "department_id", "primary_office_id", "is_active",
                                                                 "employment_status", "hired_at")})
    if "role" in data and data["role"] is not None and data["role"] != emp.user.role:
        changes["role"] = {"old": emp.user.role, "new": data["role"]}
        emp.user.role = data["role"]
        emp.user.token_version += 1
    if data.get("is_active") is not None:
        emp.user.is_active = data["is_active"]
        if not data["is_active"]:
            emp.user.token_version += 1
    if "full_name" in data and data["full_name"]:
        emp.user.full_name = data["full_name"]
    if data.get("office_ids") is not None:
        _set_offices(db, p.org_id, emp.id, data["office_ids"])
        changes["office_ids"] = data["office_ids"]
    if data.get("managed_department_ids") is not None:
        _set_managed(db, p.org_id, emp.user, data["managed_department_ids"])
        changes["managed_department_ids"] = data["managed_department_ids"]
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="employee.updated", entity_type="employee", entity_id=emp.id, changes=changes)
    db.commit()
    db.refresh(emp)
    return serialize_employee(db, emp)


@router.post("/{employee_id}/resend-invite/", response_model=EmployeeCreated)
def resend_invite(employee_id: int, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    emp = get_employee_or_404(db, p, employee_id)
    if emp.user.invite_token_hash is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee already activated")
    raw, hashed = new_invite_token()
    emp.user.invite_token_hash, emp.user.invite_expires_at = hashed, utcnow() + timedelta(hours=get_settings().invite_token_hours)
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="employee.invite_resent", entity_type="employee", entity_id=emp.id)
    db.commit()
    url = f"{get_settings().frontend_url}/accept-invite?token={raw}"
    send_email(emp.user.email, "Your GeoAttend invitation", f"Set your password to join: {url}\n")
    return EmployeeCreated(**serialize_employee(db, emp).model_dump(), invite_url=url)


@router.delete("/{employee_id}/", status_code=204)
def delete_employee(employee_id: int, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    """Offboard: deactivates the employee and their login, revokes tokens and devices.
    Attendance history is retained for payroll/compliance (see data retention policy)."""
    emp = get_employee_or_404(db, p, employee_id)
    if emp.user.role == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The owner account cannot be removed")
    if p.employee and emp.id == p.employee.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove yourself")
    emp.is_active = False
    emp.employment_status = EmploymentStatus.TERMINATED
    emp.user.is_active = False
    emp.user.token_version += 1
    for dev in db.scalars(select(DeviceRegistration).where(DeviceRegistration.employee_id == emp.id)).all():
        dev.is_active, dev.push_token = False, None
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="employee.deactivated", entity_type="employee", entity_id=emp.id)
    db.commit()
