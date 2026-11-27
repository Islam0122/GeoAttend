"""Subscription plans and enforced limits. No payment processor is integrated: plan changes are
applied by the workspace owner and recorded in the audit log."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Employee, Office, Organization
from app.models.enums import SubscriptionPlan


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    monthly_price_usd: int | None   # None = contact sales
    max_employees: int | None       # None = unlimited
    max_offices: int | None
    features: tuple[str, ...]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["features"] = list(self.features)
        return d


PLANS: dict[SubscriptionPlan, Plan] = {
    SubscriptionPlan.FREE: Plan("FREE", "Free", 0, 10, 1, ("GPS check-in/out", "1 office geofence", "Daily reports")),
    SubscriptionPlan.STARTER: Plan("STARTER", "Starter", 49, 50, 3, ("Everything in Free", "3 offices", "Weekly & monthly reports", "CSV export")),
    SubscriptionPlan.BUSINESS: Plan("BUSINESS", "Business", 199, 500, 25, ("Everything in Starter", "Manager approval workflows", "Departments & multiple schedules", "Audit log")),
    SubscriptionPlan.ENTERPRISE: Plan("ENTERPRISE", "Enterprise", None, None, None, ("Unlimited employees & offices", "Google Workspace SSO", "Custom data retention", "Priority support")),
}


def usage(db: Session, org_id: int) -> dict[str, int]:
    return {
        "employees": db.scalar(select(func.count()).select_from(Employee).where(Employee.organization_id == org_id, Employee.is_active.is_(True))) or 0,
        "offices": db.scalar(select(func.count()).select_from(Office).where(Office.organization_id == org_id, Office.is_active.is_(True))) or 0,
    }


def enforce(db: Session, org_id: int, resource: str) -> None:
    org = db.get(Organization, org_id)
    plan = PLANS[org.subscription_plan]
    limit = plan.max_employees if resource == "employees" else plan.max_offices
    if limit is not None and usage(db, org_id)[resource] >= limit:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, {"code": "PLAN_LIMIT_REACHED", "resource": resource, "limit": limit, "plan": plan.code,
                                                               "message": f"The {plan.name} plan allows {limit} active {resource}. Upgrade under Billing."})
