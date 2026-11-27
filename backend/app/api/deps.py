"""Request dependencies: authentication + re-exported RBAC helpers."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import decode_token
from app.models import Employee, Organization, User
from app.permissions.rbac import (  # noqa: F401  (re-exported for endpoints)
    ADMIN_ROLES,
    HR_ROLES,
    PERMISSIONS,
    READ_ALL_ROLES,
    REPORT_ROLES,
    STAFF_ROLES,
    Principal,
    can_review_employee,
    can_view_employee,
    scope_employees,
)

bearer = HTTPBearer(auto_error=False)


def get_principal(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(creds.credentials, "access")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from None
    user = db.get(User, int(payload["sub"]))
    # Organization membership is re-validated on every request from the database row.
    if user is None or not user.is_active or user.organization_id != payload.get("org") or user.token_version != payload.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    org = db.get(Organization, user.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Organization is disabled")
    rate_limit.check(f"user:{user.id}", get_settings().rate_limit_default)
    emp = db.scalar(select(Employee).where(Employee.user_id == user.id))
    request.state.user_id = user.id
    request.state.org_id = user.organization_id
    return Principal(user=user, employee=emp)


def require_roles(*roles):
    allowed = set(roles)

    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if p.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return p

    return dep


def require_permission(permission: str):
    return require_roles(*PERMISSIONS[permission])


require_admin = require_roles(*ADMIN_ROLES)
require_hr = require_roles(*HR_ROLES)
require_staff = require_roles(*STAFF_ROLES)
require_reports = require_roles(*REPORT_ROLES)
require_viewer = require_roles(*(STAFF_ROLES | READ_ALL_ROLES))


def require_employee(p: Principal = Depends(get_principal)) -> Principal:
    if p.employee is None or not p.employee.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No active employee profile for this account")
    return p


def get_employee_or_404(db: Session, p: Principal, employee_id: int) -> Employee:
    emp = db.get(Employee, employee_id)
    if emp is None or not can_view_employee(p, emp):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return emp


def pagination(page: int = 1, page_size: int = 50) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid pagination")
    return page, page_size


def location_rate_limit(p: Principal = Depends(get_principal)) -> Principal:
    rate_limit.check(f"loc:{p.user.id}", get_settings().rate_limit_locations)
    return p
