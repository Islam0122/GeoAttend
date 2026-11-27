from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require_reports, scope_employees
from app.core.db import get_db
from app.core.timeutils import local_date, utcnow
from app.models import Employee, ReportSnapshot
from app.models.enums import ReportType
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports"])


def _visible_ids(db: Session, p: Principal) -> set[int] | None:
    """None = whole organization (HR/admin)."""
    if p.is_org_wide:
        return None
    return set(db.scalars(scope_employees(select(Employee.id), p)).all())


def _today(db: Session, p: Principal) -> date:
    return local_date(utcnow(), reports.org_tz(db, p.org_id))


def _respond(data: dict, fmt: str, filename: str):
    if fmt == "csv":
        return PlainTextResponse(reports.to_csv(data["rows"]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    return data


def _range(start: date | None, end: date | None, default: tuple[date, date]) -> tuple[date, date]:
    s, e = start or default[0], end or default[1]
    if e < s or (e - s).days > 370:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid date range (max 370 days)")
    return s, e


@router.get("/daily/")
def daily(day: date | None = Query(default=None, alias="date"), department_id: int | None = None, office_id: int | None = None,
          format: str = "json", p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    d = day or _today(db, p)
    return _respond(reports.daily(db, p.org_id, d, _visible_ids(db, p), department_id, office_id), format, f"daily-{d}")


@router.get("/weekly/")
def weekly(week_of: date | None = None, department_id: int | None = None, format: str = "json", p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    s, e = reports.week_bounds(week_of or _today(db, p))
    return _respond(reports.period_summary(db, p.org_id, s, e, _visible_ids(db, p), department_id), format, f"weekly-{s}")


@router.get("/monthly/")
def monthly(month: date | None = None, department_id: int | None = None, format: str = "json", p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    s, e = reports.month_bounds(month or _today(db, p))
    return _respond(reports.period_summary(db, p.org_id, s, e, _visible_ids(db, p), department_id), format, f"monthly-{s}")


@router.get("/late-arrivals/")
def late_arrivals(start: date | None = None, end: date | None = None, department_id: int | None = None, format: str = "json",
                  p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    t = _today(db, p)
    s, e = _range(start, end, (t - timedelta(days=30), t))
    return _respond(reports.exceptions(db, p.org_id, s, e, "late", _visible_ids(db, p), department_id), format, f"late-{s}-{e}")


@router.get("/early-leaves/")
def early_leaves(start: date | None = None, end: date | None = None, department_id: int | None = None, format: str = "json",
                 p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    t = _today(db, p)
    s, e = _range(start, end, (t - timedelta(days=30), t))
    return _respond(reports.exceptions(db, p.org_id, s, e, "early", _visible_ids(db, p), department_id), format, f"early-{s}-{e}")


@router.get("/snapshots/")
def snapshots(report_type: ReportType | None = None, p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    if not p.is_org_wide:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    q = select(ReportSnapshot).where(ReportSnapshot.organization_id == p.org_id)
    if report_type:
        q = q.where(ReportSnapshot.report_type == report_type)
    return [{"id": s.id, "report_type": s.report_type.value, "period_start": s.period_start, "period_end": s.period_end, "generated_at": s.generated_at,
             "data": s.data} for s in db.scalars(q.order_by(ReportSnapshot.period_start.desc()).limit(60)).all()]


def _period(db: Session, p: Principal, start: date | None, end: date | None, days: int = 30) -> tuple[date, date]:
    t = _today(db, p)
    return _range(start, end, (t - timedelta(days=days - 1), t))


@router.get("/absences/")
def absences(start: date | None = None, end: date | None = None, department_id: int | None = None, format: str = "json",
             p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    s, e = _period(db, p, start, end)
    return _respond(reports.absences(db, p.org_id, s, e, _visible_ids(db, p), department_id), format, f"absences-{s}-{e}")


@router.get("/overtime/")
def overtime(start: date | None = None, end: date | None = None, department_id: int | None = None, format: str = "json",
             p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    s, e = _period(db, p, start, end)
    return _respond(reports.overtime(db, p.org_id, s, e, _visible_ids(db, p), department_id), format, f"overtime-{s}-{e}")


@router.get("/trends/")
def trends(start: date | None = None, end: date | None = None, department_id: int | None = None,
           p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    s, e = _period(db, p, start, end, days=14)
    if (e - s).days > 92:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Trend range is limited to 93 days")
    return reports.trends(db, p.org_id, s, e, _visible_ids(db, p), department_id)


@router.get("/departments/")
def departments(start: date | None = None, end: date | None = None, p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    s, e = _period(db, p, start, end)
    return reports.department_performance(db, p.org_id, s, e, _visible_ids(db, p))


EXPORTS = {"daily", "weekly", "monthly", "late-arrivals", "early-leaves", "absences", "overtime"}


@router.get("/export/")
def export(report: str = "daily", start: date | None = None, end: date | None = None, department_id: int | None = None,
           p: Principal = Depends(require_reports), db: Session = Depends(get_db)):
    """CSV export of any report: ?report=daily|weekly|monthly|late-arrivals|early-leaves|absences|overtime"""
    if report not in EXPORTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"report must be one of {sorted(EXPORTS)}")
    ids = _visible_ids(db, p)
    t = _today(db, p)
    if report == "daily":
        d = start or t
        data, name = reports.daily(db, p.org_id, d, ids, department_id), f"daily-{d}"
    elif report in ("weekly", "monthly"):
        s, e = (reports.week_bounds if report == "weekly" else reports.month_bounds)(start or t)
        data, name = reports.period_summary(db, p.org_id, s, e, ids, department_id), f"{report}-{s}"
    else:
        s, e = _period(db, p, start, end)
        if report in ("late-arrivals", "early-leaves"):
            data = reports.exceptions(db, p.org_id, s, e, "late" if report == "late-arrivals" else "early", ids, department_id)
        else:
            data = (reports.absences if report == "absences" else reports.overtime)(db, p.org_id, s, e, ids, department_id)
        name = f"{report}-{s}-{e}"
    return _respond(data, "csv", name)


me_router = APIRouter(prefix="/reports/me", tags=["reports"])


@me_router.get("/")
def my_report(start: date | None = None, end: date | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Employee self-service report (own attendance only)."""
    if p.employee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    t = _today(db, p)
    s, e = _range(start, end, reports.month_bounds(t))
    summary = reports.period_summary(db, p.org_id, s, e, {p.employee.id})
    return {**summary, "trend": reports.trends(db, p.org_id, s, min(e, t), {p.employee.id})["series"] if s <= t else []}
