"""Role-based access control + tenant/department scoping. The organization always comes from the
verified token's user row, never from request input."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select

from app.models import Employee, User
from app.models.enums import Role

ADMIN_ROLES = frozenset({Role.OWNER, Role.ADMIN})
HR_ROLES = frozenset({Role.OWNER, Role.ADMIN, Role.HR})
STAFF_ROLES = frozenset({Role.OWNER, Role.ADMIN, Role.HR, Role.MANAGER})        # can review/approve
READ_ALL_ROLES = frozenset({Role.OWNER, Role.ADMIN, Role.HR, Role.ACCOUNTANT})  # org-wide read
REPORT_ROLES = STAFF_ROLES | {Role.ACCOUNTANT}

# Capability matrix (documented + enforced through the dependencies below).
PERMISSIONS: dict[str, frozenset[Role]] = {
    "organization.manage": ADMIN_ROLES,
    "billing.manage": frozenset({Role.OWNER}),
    "offices.manage": ADMIN_ROLES,
    "settings.manage": ADMIN_ROLES,
    "employees.manage": HR_ROLES,
    "schedules.manage": HR_ROLES,
    "employees.view": STAFF_ROLES | {Role.ACCOUNTANT},
    "attendance.review": STAFF_ROLES,
    "monitoring.view": STAFF_ROLES,
    "reports.view": REPORT_ROLES,
    "audit.view": ADMIN_ROLES,
}


@dataclass
class Principal:
    user: User
    employee: Employee | None

    @property
    def org_id(self) -> int:
        return self.user.organization_id

    @property
    def role(self) -> Role:
        return self.user.role

    @property
    def is_org_wide(self) -> bool:
        """May *read* every employee of the organization."""
        return self.user.role in READ_ALL_ROLES

    @property
    def is_hr(self) -> bool:
        return self.user.role in HR_ROLES

    @property
    def managed_department_ids(self) -> set[int]:
        return {d.id for d in self.user.managed_departments}

    def can(self, permission: str) -> bool:
        return self.user.role in PERMISSIONS[permission]


def scope_employees(stmt: Select, p: Principal) -> Select:
    """Restrict an Employee-joined query to what the principal may see."""
    stmt = stmt.where(Employee.organization_id == p.org_id)
    if p.is_org_wide:
        return stmt
    if p.role == Role.MANAGER:
        ids = p.managed_department_ids
        if p.employee is not None:
            return stmt.where((Employee.department_id.in_(ids)) | (Employee.id == p.employee.id))
        return stmt.where(Employee.department_id.in_(ids))
    return stmt.where(Employee.id == (p.employee.id if p.employee else -1))


def can_view_employee(p: Principal, emp: Employee) -> bool:
    if emp.organization_id != p.org_id:
        return False
    if p.is_org_wide:
        return True
    if p.employee is not None and emp.id == p.employee.id:
        return True
    return p.role == Role.MANAGER and emp.department_id in p.managed_department_ids


def can_review_employee(p: Principal, emp: Employee) -> bool:
    """Approve/review someone's attendance: staff with visibility, never yourself."""
    if p.role not in STAFF_ROLES or not can_view_employee(p, emp):
        return False
    return not (p.employee is not None and p.employee.id == emp.id)
