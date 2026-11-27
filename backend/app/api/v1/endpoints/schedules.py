from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    get_employee_or_404,
    get_principal,
    require_employee,
    require_hr,
    require_staff,
    scope_employees,
)
from app.core.db import get_db
from app.core.timeutils import local_date, utcnow
from app.models import (
    Department,
    Employee,
    LeaveRequest,
    ScheduleAssignment,
    ScheduleDay,
    WorkSchedule,
)
from app.models.enums import RequestStatus, Role
from app.schemas.schedule import (
    AbsenceIn,
    AbsenceOut,
    AssignmentIn,
    AssignmentOut,
    ReviewIn,
    ScheduleIn,
    ScheduleOut,
    SchedulePatch,
    ShiftOut,
)
from app.services import attendance_service as att
from app.services.audit import audit, diff
from app.services.notifications import notify_employee
from app.services.schedule_service import employee_timezone, shift_for_date

router = APIRouter(tags=["schedules"])


def _sched(db: Session, p: Principal, sid: int) -> WorkSchedule:
    s = db.get(WorkSchedule, sid)
    if s is None or s.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return s


@router.get("/schedules/", response_model=list[ScheduleOut])
def list_schedules(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(WorkSchedule).where(WorkSchedule.organization_id == p.org_id).order_by(WorkSchedule.name)).all()


@router.post("/schedules/", response_model=ScheduleOut, status_code=201)
def create_schedule(body: ScheduleIn, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    s = WorkSchedule(organization_id=p.org_id, **body.model_dump(exclude={"days"}))
    s.days = [ScheduleDay(**d.model_dump()) for d in body.days]
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Schedule name already exists") from None
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="schedule.created", entity_type="work_schedule", entity_id=s.id, changes=body.model_dump())
    db.commit()
    return s


@router.get("/schedules/me/", response_model=list[ShiftOut])
def my_schedule(days: int = 14, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    settings = att.org_settings(db, p.org_id)
    emp = p.employee
    today = local_date(utcnow(), employee_timezone(db, emp))
    out = []
    for i in range(min(max(days, 1), 62)):
        sh = shift_for_date(db, emp, today + timedelta(days=i), settings)
        if sh:
            out.append(ShiftOut(work_date=sh.work_date, start=sh.start, end=sh.end, break_start=sh.break_start, break_end=sh.break_end, timezone=sh.timezone,
                                schedule_id=sh.schedule_id, tracking_window_start=sh.window_start, tracking_window_end=sh.window_end))
    return out


@router.get("/schedules/assignments/", response_model=list[AssignmentOut])
def list_assignments(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(ScheduleAssignment).where(ScheduleAssignment.organization_id == p.org_id).order_by(ScheduleAssignment.effective_from.desc())).all()


@router.post("/schedules/assign/", response_model=AssignmentOut, status_code=201)
@router.post("/schedules/assignments/", response_model=AssignmentOut, status_code=201, include_in_schema=False)
def create_assignment(body: AssignmentIn, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    _sched(db, p, body.schedule_id)
    if body.employee_id:
        get_employee_or_404(db, p, body.employee_id)
    if body.department_id:
        d = db.get(Department, body.department_id)
        if d is None or d.organization_id != p.org_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    a = ScheduleAssignment(organization_id=p.org_id, **body.model_dump())
    db.add(a)
    db.flush()
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="schedule.assigned", entity_type="schedule_assignment", entity_id=a.id, changes=body.model_dump())
    db.commit()
    return a


@router.delete("/schedules/assignments/{assignment_id}/", status_code=204)
def delete_assignment(assignment_id: int, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    a = db.get(ScheduleAssignment, assignment_id)
    if a is None or a.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="schedule.unassigned", entity_type="schedule_assignment", entity_id=a.id)
    db.delete(a)
    db.commit()


@router.get("/schedules/{schedule_id}/", response_model=ScheduleOut)
def get_schedule(schedule_id: int, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return _sched(db, p, schedule_id)


@router.patch("/schedules/{schedule_id}/", response_model=ScheduleOut)
def patch_schedule(schedule_id: int, body: SchedulePatch, p: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    s = _sched(db, p, schedule_id)
    data = body.model_dump(exclude_unset=True)
    days = data.pop("days", None)
    changes = diff(s, {k: v for k, v in data.items() if v is not None})
    if days is not None:
        if len({d["weekday"] for d in days}) != len(days):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate weekday")
        s.days.clear()
        db.flush()
        s.days.extend(ScheduleDay(**d) for d in days)
        changes["days"] = days
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="schedule.updated", entity_type="work_schedule", entity_id=s.id, changes=changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Schedule name already exists") from None
    db.refresh(s)
    return s


# ---------------------------------------------------------- leave requests ----

def _leave_out(a: LeaveRequest, name: str | None) -> AbsenceOut:
    o = AbsenceOut.model_validate(a)
    o.employee_name = name
    return o


@router.get("/leave-requests/", response_model=list[AbsenceOut])
def list_leave(status_filter: RequestStatus | None = Query(default=None, alias="status"), mine: bool = False,
               p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = scope_employees(select(LeaveRequest, Employee.full_name).join(Employee, Employee.id == LeaveRequest.employee_id), p).where(LeaveRequest.organization_id == p.org_id)
    if mine:
        q = q.where(LeaveRequest.employee_id == (p.employee.id if p.employee else -1))
    if status_filter:
        q = q.where(LeaveRequest.status == status_filter)
    return [_leave_out(a, n) for a, n in db.execute(q.order_by(LeaveRequest.starts_at.desc()).limit(500)).all()]


@router.post("/leave-requests/", response_model=AbsenceOut, status_code=201)
def create_absence(body: AbsenceIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if body.employee_id is None or (p.employee and body.employee_id == p.employee.id):
        if p.employee is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "employee_id is required")
        emp, auto_approve = p.employee, False
    else:
        if not p.is_hr:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only HR can register absences for others")
        emp, auto_approve = get_employee_or_404(db, p, body.employee_id), True
    a = LeaveRequest(organization_id=p.org_id, employee_id=emp.id, type=body.type, starts_at=body.starts_at, ends_at=body.ends_at, reason=body.reason,
                      status=RequestStatus.APPROVED if auto_approve else RequestStatus.PENDING,
                      reviewed_by_id=p.user.id if auto_approve else None, reviewed_at=utcnow() if auto_approve else None)
    db.add(a)
    db.flush()
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="leave.created", entity_type="leave_request", entity_id=a.id, changes=body.model_dump())
    db.commit()
    return _leave_out(a, emp.full_name)


@router.post("/leave-requests/{absence_id}/cancel/", response_model=AbsenceOut)
def cancel_leave(absence_id: int, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    a = db.get(LeaveRequest, absence_id)
    if a is None or a.employee_id != p.employee.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")
    if a.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending requests can be cancelled")
    a.status = RequestStatus.REJECTED
    a.reason = ((a.reason or "") + " [cancelled by employee]").strip()
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="leave.cancelled", entity_type="leave_request", entity_id=a.id)
    db.commit()
    return _leave_out(a, p.employee.full_name)


@router.post("/leave-requests/{absence_id}/review/", response_model=AbsenceOut)
def review_absence(absence_id: int, body: ReviewIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    a = db.get(LeaveRequest, absence_id)
    if a is None or a.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")
    emp = get_employee_or_404(db, p, a.employee_id)
    if p.role == Role.MANAGER and p.employee and emp.id == p.employee.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot approve your own request")
    if a.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reviewed")
    a.status = RequestStatus.APPROVED if body.approve else RequestStatus.REJECTED
    a.reviewed_by_id, a.reviewed_at = p.user.id, utcnow()
    audit(db, org_id=p.org_id, actor_id=p.user.id, action=f"leave.{a.status.value.lower()}", entity_type="leave_request", entity_id=a.id, changes={"comment": body.comment})
    notify_employee(db, emp, type="ABSENCE_REVIEWED", title=f"Request {a.status.value.lower()}", body=f"Your {a.type.value.lower().replace('_', ' ')} request was {a.status.value.lower()}.",
                    data={"leave_request_id": a.id})
    db.commit()
    return _leave_out(a, emp.full_name)
