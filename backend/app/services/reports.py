"""Attendance reports computed from AttendanceRecord (single source of truth)."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRecord,
    Employee,
    Office,
    Organization,
    OrganizationSettings,
)
from app.models.enums import AttendanceStatus
from app.services.schedule_service import shift_for_date

PRESENT_LIKE = {AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.HALF_DAY, AttendanceStatus.INCOMPLETE, AttendanceStatus.UNSCHEDULED}


def _employees(db: Session, org_id: int, employee_ids: set[int] | None, department_id: int | None = None) -> list[Employee]:
    q = select(Employee).where(Employee.organization_id == org_id, Employee.is_active.is_(True)).order_by(Employee.full_name)
    if employee_ids is not None:
        q = q.where(Employee.id.in_(employee_ids or {-1}))
    if department_id:
        q = q.where(Employee.department_id == department_id)
    return list(db.scalars(q).unique().all())


def _records(db: Session, org_id: int, emp_ids: list[int], start: date, end: date) -> list[AttendanceRecord]:
    return list(db.scalars(select(AttendanceRecord).where(
        AttendanceRecord.organization_id == org_id, AttendanceRecord.employee_id.in_(emp_ids or [-1]),
        AttendanceRecord.work_date >= start, AttendanceRecord.work_date <= end).order_by(AttendanceRecord.work_date)).all())


def _office_names(db: Session, org_id: int) -> dict[int, str]:
    return dict(db.execute(select(Office.id, Office.name).where(Office.organization_id == org_id)).all())


def daily(db: Session, org_id: int, day: date, employee_ids: set[int] | None = None, department_id: int | None = None, office_id: int | None = None) -> dict:
    settings = db.get(OrganizationSettings, org_id) or OrganizationSettings(organization_id=org_id)
    emps = _employees(db, org_id, employee_ids, department_id)
    recs = {r.employee_id: r for r in _records(db, org_id, [e.id for e in emps], day, day)}
    offices = _office_names(db, org_id)
    rows, summary = [], defaultdict(int)
    for e in emps:
        r = recs.get(e.id)
        shift = None if r else shift_for_date(db, e, day, settings)
        if r is None and shift is None:
            continue  # not scheduled
        oid = r.office_id if r else e.primary_office_id
        if office_id and oid != office_id:
            continue
        status = r.status.value if r else "NOT_CHECKED_IN"
        summary[status] += 1
        rows.append({
            "employee_id": e.id, "employee_name": e.full_name, "employee_code": e.employee_code,
            "department": e.department.name if e.department else None, "office": offices.get(oid) if oid else None,
            "scheduled_start": (r.scheduled_start if r else shift.start).isoformat() if (r and r.scheduled_start) or shift else None,
            "scheduled_end": (r.scheduled_end if r else shift.end).isoformat() if (r and r.scheduled_end) or shift else None,
            "actual_check_in": r.actual_check_in.isoformat() if r and r.actual_check_in else None,
            "actual_check_out": r.actual_check_out.isoformat() if r and r.actual_check_out else None,
            "worked_minutes": r.worked_minutes if r else 0, "break_minutes": r.break_minutes if r else 0,
            "late_minutes": r.late_minutes if r else 0, "early_departure_minutes": r.early_departure_minutes if r else 0,
            "overtime_minutes": r.overtime_minutes if r else 0, "status": status, "record_id": r.id if r else None,
            "shift": "Unscheduled" if r and r.is_unscheduled else (f"{(r.scheduled_start if r else shift.start).isoformat()}" if (r and r.scheduled_start) or shift else None),
            "early_arrival_minutes": r.early_arrival_minutes if r else 0,
            "total_presence_minutes": r.presence_minutes if r else 0,
            "temporary_exit_minutes": r.temporary_exit_minutes if r else 0,
            "payable_minutes": r.worked_minutes if r else 0,
        })
    return {"date": day.isoformat(), "rows": rows, "summary": dict(summary), "scheduled": len(rows)}


def period_summary(db: Session, org_id: int, start: date, end: date, employee_ids: set[int] | None = None, department_id: int | None = None) -> dict:
    emps = _employees(db, org_id, employee_ids, department_id)
    by_emp: dict[int, list[AttendanceRecord]] = defaultdict(list)
    for r in _records(db, org_id, [e.id for e in emps], start, end):
        by_emp[r.employee_id].append(r)
    rows = []
    totals = defaultdict(int)
    for e in emps:
        rs = by_emp.get(e.id, [])
        row = {
            "employee_id": e.id, "employee_name": e.full_name, "department": e.department.name if e.department else None,
            "days_recorded": len(rs),
            "present_days": sum(1 for r in rs if r.status in PRESENT_LIKE),
            "late_days": sum(1 for r in rs if r.late_minutes > 0),
            "late_minutes": sum(r.late_minutes for r in rs),
            "early_leave_days": sum(1 for r in rs if r.early_departure_minutes > 0),
            "early_departure_minutes": sum(r.early_departure_minutes for r in rs),
            "absent_days": sum(1 for r in rs if r.status == AttendanceStatus.ABSENT),
            "half_days": sum(1 for r in rs if r.status == AttendanceStatus.HALF_DAY),
            "leave_days": sum(1 for r in rs if r.status == AttendanceStatus.ON_LEAVE),
            "incomplete_days": sum(1 for r in rs if r.status == AttendanceStatus.INCOMPLETE),
            "location_unavailable_days": sum(1 for r in rs if r.status == AttendanceStatus.LOCATION_UNAVAILABLE),
            "pending_confirmation_days": sum(1 for r in rs if r.status == AttendanceStatus.PENDING_CONFIRMATION),
            "worked_minutes": sum(r.worked_minutes for r in rs),
            "break_minutes": sum(r.break_minutes for r in rs),
            "overtime_minutes": sum(r.overtime_minutes for r in rs),
            "total_working_days": sum(1 for r in rs if r.status != AttendanceStatus.ON_LEAVE),
            "unscheduled_days": sum(1 for r in rs if r.is_unscheduled),
            "presence_minutes": sum(r.presence_minutes for r in rs),
            "temporary_exit_minutes": sum(r.temporary_exit_minutes for r in rs),
        }
        expected = row["total_working_days"] - row["unscheduled_days"]
        row["attendance_percentage"] = round(100 * (row["present_days"] - row["unscheduled_days"]) / expected, 1) if expected > 0 else None
        for k, v in row.items():
            if isinstance(v, int) and not isinstance(v, bool) and k != "employee_id":
                totals[k] += v
        rows.append(row)
    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows, "totals": dict(totals)}


def exceptions(db: Session, org_id: int, start: date, end: date, kind: str, employee_ids: set[int] | None = None, department_id: int | None = None) -> dict:
    emps = {e.id: e for e in _employees(db, org_id, employee_ids, department_id)}
    offices = _office_names(db, org_id)
    rows = []
    for r in _records(db, org_id, list(emps), start, end):
        minutes = r.late_minutes if kind == "late" else r.early_departure_minutes
        if minutes <= 0:
            continue
        e = emps[r.employee_id]
        rows.append({
            "record_id": r.id, "work_date": r.work_date.isoformat(), "employee_id": e.id, "employee_name": e.full_name,
            "department": e.department.name if e.department else None, "office": offices.get(r.office_id) if r.office_id else None,
            "scheduled": (r.scheduled_start if kind == "late" else r.scheduled_end).isoformat() if (r.scheduled_start if kind == "late" else r.scheduled_end) else None,
            "actual": (r.actual_check_in if kind == "late" else r.actual_check_out).isoformat() if (r.actual_check_in if kind == "late" else r.actual_check_out) else None,
            "minutes": minutes, "status": r.status.value,
        })
    rows.sort(key=lambda x: (x["work_date"], -x["minutes"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "kind": kind, "rows": rows, "count": len(rows), "total_minutes": sum(x["minutes"] for x in rows)}


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_bounds(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def org_tz(db: Session, org_id: int) -> str:
    org = db.get(Organization, org_id)
    return org.timezone if org else "UTC"


ABSENCE_STATUSES = {AttendanceStatus.ABSENT: "ABSENT", AttendanceStatus.ON_LEAVE: "ON_LEAVE", AttendanceStatus.LOCATION_UNAVAILABLE: "LOCATION_UNAVAILABLE"}


def absences(db: Session, org_id: int, start: date, end: date, employee_ids: set[int] | None = None, department_id: int | None = None) -> dict:
    emps = {e.id: e for e in _employees(db, org_id, employee_ids, department_id)}
    rows = [{"record_id": r.id, "work_date": r.work_date.isoformat(), "employee_id": r.employee_id, "employee_name": emps[r.employee_id].full_name,
             "department": emps[r.employee_id].department.name if emps[r.employee_id].department else None, "status": r.status.value,
             "needs_review": r.status == AttendanceStatus.LOCATION_UNAVAILABLE}
            for r in _records(db, org_id, list(emps), start, end) if r.status in ABSENCE_STATUSES]
    by_kind: dict[str, int] = defaultdict(int)
    for x in rows:
        by_kind[x["status"]] += 1
    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows, "count": len(rows), "by_status": dict(by_kind)}


def overtime(db: Session, org_id: int, start: date, end: date, employee_ids: set[int] | None = None, department_id: int | None = None) -> dict:
    emps = {e.id: e for e in _employees(db, org_id, employee_ids, department_id)}
    rows = [{"record_id": r.id, "work_date": r.work_date.isoformat(), "employee_id": r.employee_id, "employee_name": emps[r.employee_id].full_name,
             "department": emps[r.employee_id].department.name if emps[r.employee_id].department else None,
             "scheduled_minutes": r.scheduled_minutes, "worked_minutes": r.worked_minutes, "overtime_minutes": r.overtime_minutes}
            for r in _records(db, org_id, list(emps), start, end) if r.overtime_minutes > 0]
    rows.sort(key=lambda x: (x["work_date"], -x["overtime_minutes"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows, "count": len(rows), "total_minutes": sum(x["overtime_minutes"] for x in rows)}


def trends(db: Session, org_id: int, start: date, end: date, employee_ids: set[int] | None = None, department_id: int | None = None) -> dict:
    """Per-day series for charts: present / late / absent / on leave / average worked / overtime."""
    emps = _employees(db, org_id, employee_ids, department_id)
    days: dict[date, dict] = {}
    d = start
    while d <= end:
        days[d] = {"date": d.isoformat(), "records": 0, "present": 0, "late": 0, "absent": 0, "on_leave": 0, "location_unavailable": 0,
                   "worked_minutes": 0, "overtime_minutes": 0, "late_minutes": 0}
        d += timedelta(days=1)
    for r in _records(db, org_id, [e.id for e in emps], start, end):
        x = days[r.work_date]
        x["records"] += 1
        x["present"] += r.status in PRESENT_LIKE
        x["late"] += r.late_minutes > 0
        x["absent"] += r.status == AttendanceStatus.ABSENT
        x["on_leave"] += r.status == AttendanceStatus.ON_LEAVE
        x["location_unavailable"] += r.status == AttendanceStatus.LOCATION_UNAVAILABLE
        x["worked_minutes"] += r.worked_minutes
        x["overtime_minutes"] += r.overtime_minutes
        x["late_minutes"] += r.late_minutes
    series = []
    for x in days.values():
        x["avg_worked_minutes"] = round(x["worked_minutes"] / x["present"]) if x["present"] else 0
        x["attendance_rate"] = round(100 * x["present"] / x["records"], 1) if x["records"] else None
        series.append(x)
    return {"start": start.isoformat(), "end": end.isoformat(), "series": series}


def department_performance(db: Session, org_id: int, start: date, end: date, employee_ids: set[int] | None = None) -> dict:
    emps = _employees(db, org_id, employee_ids)
    dept_of = {e.id: (e.department.name if e.department else "No department") for e in emps}
    agg: dict[str, dict] = defaultdict(lambda: {"employees": set(), "records": 0, "present": 0, "late": 0, "absent": 0, "worked_minutes": 0, "overtime_minutes": 0})
    for e in emps:
        agg[dept_of[e.id]]["employees"].add(e.id)
    for r in _records(db, org_id, [e.id for e in emps], start, end):
        a = agg[dept_of[r.employee_id]]
        a["records"] += 1
        a["present"] += r.status in PRESENT_LIKE
        a["late"] += r.late_minutes > 0
        a["absent"] += r.status == AttendanceStatus.ABSENT
        a["worked_minutes"] += r.worked_minutes
        a["overtime_minutes"] += r.overtime_minutes
    rows = []
    for name, a in sorted(agg.items()):
        rows.append({"department": name, "employees": len(a["employees"]), "records": a["records"],
                     "attendance_rate": round(100 * a["present"] / a["records"], 1) if a["records"] else None,
                     "punctuality_rate": round(100 * (a["present"] - a["late"]) / a["present"], 1) if a["present"] else None,
                     "late": a["late"], "absent": a["absent"],
                     "avg_worked_minutes": round(a["worked_minutes"] / a["present"]) if a["present"] else 0, "overtime_minutes": a["overtime_minutes"]})
    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows}
