from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    get_principal,
    pagination,
    require_admin,
    require_hr,
    require_roles,
)
from app.core.db import get_db
from app.models import AuditLog, Department, Employee, Organization
from app.models.enums import Role, SubscriptionPlan
from app.repositories.tenant import TenantRepository
from app.schemas.attendance import AuditLogOut
from app.schemas.common import Page
from app.schemas.org import (
    DepartmentIn,
    DepartmentOut,
    OrganizationOut,
    OrganizationPatch,
    SettingsOut,
    SettingsPatch,
)
from app.services import attendance_service as att
from app.services import plans
from app.services.audit import audit, diff

router = APIRouter(tags=["organization"])


@router.get("/plans/", tags=["public"])
def list_plans() -> list[dict]:
    """Public pricing information."""
    return [p.as_dict() for p in plans.PLANS.values()]


@router.get("/organizations/current/", response_model=OrganizationOut)
def get_org(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return db.get(Organization, p.org_id)


@router.patch("/organizations/current/", response_model=OrganizationOut)
def patch_org(body: OrganizationPatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org_id)
    changes = diff(org, body.model_dump(exclude_unset=True, exclude_none=True))
    if changes:
        audit(db, org_id=p.org_id, actor_id=p.user.id, action="organization.updated", entity_type="organization", entity_id=org.id, changes=changes)
    db.commit()
    return org


@router.get("/organizations/current/settings/", response_model=SettingsOut)
def get_settings_(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = att.org_settings(db, p.org_id)
    db.commit()
    return s


@router.patch("/organizations/current/settings/", response_model=SettingsOut)
def patch_settings(body: SettingsPatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    s = att.org_settings(db, p.org_id)
    changes = diff(s, body.model_dump(exclude_unset=True, exclude_none=True))
    if changes:
        audit(db, org_id=p.org_id, actor_id=p.user.id, action="settings.updated", entity_type="organization_settings", entity_id=p.org_id, changes=changes)
    db.commit()
    return s


class PlanChange(BaseModel):
    plan: SubscriptionPlan


@router.get("/organizations/current/billing/")
def billing(p: Principal = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    org = db.get(Organization, p.org_id)
    return {"plan": plans.PLANS[org.subscription_plan].as_dict(), "usage": plans.usage(db, p.org_id),
            "plans": [x.as_dict() for x in plans.PLANS.values()], "payment_provider_connected": False}


@router.patch("/organizations/current/billing/")
def change_plan(body: PlanChange, p: Principal = Depends(require_roles(Role.OWNER)), db: Session = Depends(get_db)) -> dict:
    org = db.get(Organization, p.org_id)
    target, use = plans.PLANS[body.plan], plans.usage(db, p.org_id)
    if (target.max_employees is not None and use["employees"] > target.max_employees) or (target.max_offices is not None and use["offices"] > target.max_offices):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Current usage exceeds the {target.name} plan limits")
    changes = diff(org, {"subscription_plan": body.plan})
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="billing.plan_changed", entity_type="organization", entity_id=org.id, changes=changes)
    db.commit()
    return billing(p, db)


# ------------------------------------------------------------- departments ----

def _dept_out(db: Session, d: Department) -> DepartmentOut:
    n = db.scalar(select(func.count()).select_from(Employee).where(Employee.department_id == d.id, Employee.is_active.is_(True))) or 0
    return DepartmentOut(id=d.id, name=d.name, employee_count=n)


@router.get("/departments/", response_model=list[DepartmentOut])
def list_departments(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    repo = TenantRepository(Department, db, p.org_id, "Department")
    return [_dept_out(db, d) for d in repo.list(order_by=Department.name)]


@router.post("/departments/", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentIn, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    d = Department(organization_id=p.org_id, name=body.name)
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Department already exists") from None
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="department.created", entity_type="department", entity_id=d.id, changes={"name": d.name})
    db.commit()
    return _dept_out(db, d)


@router.patch("/departments/{dept_id}/", response_model=DepartmentOut)
def rename_department(dept_id: int, body: DepartmentIn, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    d = TenantRepository(Department, db, p.org_id, "Department").get_or_404(dept_id)
    changes = diff(d, {"name": body.name})
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="department.updated", entity_type="department", entity_id=d.id, changes=changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Department already exists") from None
    return _dept_out(db, d)


@router.delete("/departments/{dept_id}/", status_code=204)
def delete_department(dept_id: int, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    d = TenantRepository(Department, db, p.org_id, "Department").get_or_404(dept_id)
    if _dept_out(db, d).employee_count:
        raise HTTPException(status.HTTP_409_CONFLICT, "Move active employees out of this department first")
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="department.deleted", entity_type="department", entity_id=d.id, changes={"name": d.name})
    db.delete(d)
    db.commit()


@router.get("/audit-logs/", response_model=Page[AuditLogOut])
def audit_logs(entity_type: str | None = None, pg: tuple[int, int] = Depends(pagination), p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    page, size = pg
    repo = TenantRepository(AuditLog, db, p.org_id)
    q = repo.query()
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    items = repo.list(q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()), offset=(page - 1) * size, limit=size)
    return Page(items=[AuditLogOut.model_validate(i) for i in items], total=repo.count(q), page=page, page_size=size)
