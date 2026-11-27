from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    can_review_employee,
    get_employee_or_404,
    get_principal,
    location_rate_limit,
    pagination,
    require_employee,
    require_staff,
    require_viewer,
    scope_employees,
)
from app.core.db import get_db
from app.core.timeutils import local_date, utcnow
from app.models import (
    AttendanceAnomaly,
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSession,
    Employee,
    Notification,
    Office,
    Organization,
)
from app.models.enums import (
    AnomalyStatus,
    AttendanceStatus,
    BreakType,
    ConfirmationPolicy,
    CorrectionType,
    EventTrigger,
    LocationEventType,
    PermissionStatus,
    Platform,
    RequestStatus,
    SessionConfirmation,
    SessionStatus,
)
from app.schemas.attendance import (
    AnomalyOut,
    AnomalyReviewIn,
    ApprovalIn,
    ApprovalRow,
    BreakIn,
    ConfirmIn,
    CorrectionIn,
    CorrectionOut,
    DashboardOut,
    DisputeIn,
    GpsActionIn,
    GpsActionOut,
    NotificationOut,
    RecordDetailOut,
    RecordOut,
    SessionOut,
    TeamTodayRow,
    TodayOut,
)
from app.schemas.common import Page
from app.schemas.location import LocationEventIn
from app.schemas.schedule import ReviewIn
from app.services import attendance_service as att
from app.services import checkin_service
from app.services import location_service as loc
from app.services import presence_service
from app.services.audit import audit
from app.services.notifications import notify_employee, notify_hr
from app.services.schedule_service import (
    employee_timezone,
    shift_for_date,
    shift_for_instant,
)

router = APIRouter(tags=["attendance"])


def _record_out(db: Session, r: AttendanceRecord, detail: bool = False) -> RecordOut | RecordDetailOut:
    emp = db.get(Employee, r.employee_id)
    office = db.get(Office, r.office_id) if r.office_id else None
    base = dict(
        id=r.id, employee_id=r.employee_id, employee_name=emp.full_name if emp else None,
        department_name=emp.department.name if emp and emp.department else None, office_id=r.office_id, office_name=office.name if office else None,
        work_date=r.work_date, timezone=r.timezone, scheduled_start=r.scheduled_start, scheduled_end=r.scheduled_end, scheduled_minutes=r.scheduled_minutes,
        actual_check_in=r.actual_check_in, actual_check_out=r.actual_check_out, late_minutes=r.late_minutes,
        early_departure_minutes=r.early_departure_minutes, worked_minutes=r.worked_minutes, break_minutes=r.break_minutes,
        overtime_minutes=r.overtime_minutes, status=r.status, is_finalized=r.is_finalized, is_confirmed=r.is_confirmed,
        early_arrival_minutes=r.early_arrival_minutes, presence_minutes=r.presence_minutes, temporary_exit_minutes=r.temporary_exit_minutes,
        is_unscheduled=r.is_unscheduled,
    )
    if not detail:
        return RecordOut(**base)
    return RecordDetailOut(**base, sessions=[SessionOut.model_validate(s) for s in r.sessions],
                           pending_confirmation=any(s.confirmation == SessionConfirmation.PENDING for s in r.sessions),
                           pending_checkout=any(s.status == SessionStatus.PENDING_CHECKOUT for s in r.sessions))


def _get_record(db: Session, p: Principal, record_id: int) -> AttendanceRecord:
    r = db.get(AttendanceRecord, record_id)
    if r is None or r.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance record not found")
    get_employee_or_404(db, p, r.employee_id)  # enforces self/department visibility
    return r


def _org_today(db: Session, p: Principal) -> date:
    return local_date(utcnow(), db.get(Organization, p.org_id).timezone)


@router.get("/attendance/today/", response_model=TodayOut)
def today(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """The signed-in employee's attendance for the current shift (live working time)."""
    if p.employee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    emp, now = p.employee, utcnow()
    settings = att.org_settings(db, p.org_id)
    shift = shift_for_instant(db, emp, now, settings) or shift_for_date(db, emp, local_date(now, employee_timezone(db, emp)), settings)
    record = None
    live = att.live_session(db, emp.id)
    if shift:
        record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.work_date == shift.work_date))
        if record is not None:
            att.recompute(db, record, now)
            db.commit()
    return TodayOut(
        work_date=shift.work_date if shift else None,
        shift={"start": shift.start, "end": shift.end, "break_start": shift.break_start, "break_end": shift.break_end, "timezone": shift.timezone,
               "grace_period_minutes": shift.grace_period_minutes, "tracking_window_start": shift.window_start, "tracking_window_end": shift.window_end} if shift else None,
        record=_record_out(db, record, detail=True) if record else None,
        location=loc.live_status(db, emp),
        offices=[{"id": o.id, "name": o.name, "latitude": o.latitude, "longitude": o.longitude, "radius_m": o.geofence.radius_m,
                  "max_accuracy_m": o.geofence.max_accuracy_m, "timezone": o.timezone} for o in loc.candidate_offices(db, emp)],
        actions={
            "window_open": bool(shift and shift.in_window(now)),
            "can_check_in": bool(shift and shift.in_window(now)) and (live is None or live.status == SessionStatus.AWAY),
            "can_check_out": live is not None,
            "can_start_break": live is not None and live.status == SessionStatus.OPEN,
            "can_end_break": live is not None and live.status == SessionStatus.AWAY,
            "live_session_id": live.id if live else None,
            "live_status": live.status.value if live else None,
            "confirmation_policy": settings.confirmation_policy.value,
            "checkout_requires_geofence": settings.checkout_requires_geofence,
            "consent_granted": bool((c := loc.current_consent(db, emp.id)) and c.granted),
        },
        server_time=now,
    )


def _gps_action(body: GpsActionIn, p: Principal, db: Session, action: LocationEventType) -> JSONResponse:
    if p.employee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    if not att.org_settings(db, p.org_id).manual_actions_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "MANUAL_DISABLED",
                                                       "message": "Automatic Attendance Mode is active: work time is recorded automatically."})
    try:
        perm = PermissionStatus(body.permission_status)
    except ValueError:
        perm = PermissionStatus.UNKNOWN
    item = LocationEventIn(client_event_id=body.event_uuid, device_id=body.device_id, latitude=body.latitude, longitude=body.longitude,
                           accuracy=body.accuracy, recorded_at=body.recorded_at, platform=Platform.WEB, permission_status=perm,
                           trigger=EventTrigger.MANUAL)
    res = checkin_service.perform(db, p.employee.id, item, action, utcnow())
    db.commit()  # rejected attempts are stored too (audit + suspicious-pattern detection)
    return JSONResponse(GpsActionOut(**res.as_dict()).model_dump(mode="json"), status_code=res.http_status)


@router.post("/attendance/manual-check-in/", response_model=GpsActionOut, status_code=201, include_in_schema=True)
@router.post("/attendance/check-in/", response_model=GpsActionOut, status_code=201,
             responses={200: {"description": "Duplicate (idempotent replay)"}, 409: {"description": "Already checked in"},
                        422: {"description": "GPS_ACCURACY_LOW / OUTSIDE_GEOFENCE / validation failure"}})
def check_in(body: GpsActionIn, p: Principal = Depends(location_rate_limit), db: Session = Depends(get_db)):
    return _gps_action(body, p, db, LocationEventType.CHECK_IN)


@router.post("/attendance/manual-check-out/", response_model=GpsActionOut, status_code=201)
@router.post("/attendance/check-out/", response_model=GpsActionOut, status_code=201)
def check_out(body: GpsActionIn, p: Principal = Depends(location_rate_limit), db: Session = Depends(get_db)):
    return _gps_action(body, p, db, LocationEventType.CHECK_OUT)


@router.post("/attendance/break/start/", response_model=RecordDetailOut)
def break_start(body: BreakIn, p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    loc.lock_employee(db, p.employee.id)
    try:
        s = att.start_break(db, p.employee, kind=BreakType(body.type), at=utcnow(), now=utcnow())
    except att.AttendanceError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code.upper(), "message": str(exc)}) from None
    db.commit()
    return _record_out(db, s.record, detail=True)


@router.post("/attendance/break/end/", response_model=RecordDetailOut)
def break_end(p: Principal = Depends(require_employee), db: Session = Depends(get_db)):
    loc.lock_employee(db, p.employee.id)
    try:
        s = att.end_break(db, p.employee, at=utcnow(), now=utcnow())
    except att.AttendanceError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code.upper(), "message": str(exc)}) from None
    db.commit()
    return _record_out(db, s.record, detail=True)


@router.get("/attendance/approvals/", response_model=list[ApprovalRow])
def pending_approvals(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """Sessions awaiting manager approval for employees the caller may review."""
    q = scope_employees(select(AttendanceSession, AttendanceRecord, Employee)
                        .join(AttendanceRecord, AttendanceRecord.id == AttendanceSession.record_id)
                        .join(Employee, Employee.id == AttendanceSession.employee_id), p).where(
        AttendanceSession.organization_id == p.org_id, AttendanceSession.confirmation == SessionConfirmation.PENDING)
    offices = dict(db.execute(select(Office.id, Office.name).where(Office.organization_id == p.org_id)).all())
    return [ApprovalRow(record_id=r.id, session_id=s.id, employee_id=e.id, employee_name=e.full_name, department_name=e.department.name if e.department else None,
                        work_date=r.work_date, check_in_at=s.check_in_at, check_out_at=s.check_out_at, office_name=offices.get(s.office_id), timezone=r.timezone)
            for s, r, e in db.execute(q.order_by(AttendanceSession.check_in_at.desc()).limit(500)).all() if can_review_employee(p, e)]


@router.get("/attendance/today/team/", response_model=list[TeamTodayRow])
def team_today(department_id: int | None = None, office_id: int | None = None, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    now = utcnow()
    day = _org_today(db, p)
    settings = att.org_settings(db, p.org_id)
    offices = dict(db.execute(select(Office.id, Office.name).where(Office.organization_id == p.org_id)).all())
    q = scope_employees(select(Employee), p).where(Employee.is_active.is_(True)).order_by(Employee.full_name)
    if department_id:
        q = q.where(Employee.department_id == department_id)
    rows = []
    for e in db.scalars(q).unique().all():
        shift = shift_for_instant(db, e, now, settings) or shift_for_date(db, e, day, settings)
        if shift is None:
            continue
        r = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == e.id, AttendanceRecord.work_date == shift.work_date))
        if r is not None and not r.is_finalized:
            att.recompute(db, r, now)
        oid = (r.office_id if r else None) or e.primary_office_id
        if office_id and oid != office_id:
            continue
        status_ = r.status.value if r else ("ON_LEAVE" if att.has_leave(db, e.id, shift.start, shift.end) else "NOT_CHECKED_IN")
        rows.append(TeamTodayRow(employee_id=e.id, employee_name=e.full_name, department_name=e.department.name if e.department else None,
                                 office_name=offices.get(oid) if oid else None, scheduled_start=shift.start, scheduled_end=shift.end,
                                 actual_check_in=r.actual_check_in if r else None, actual_check_out=r.actual_check_out if r else None,
                                 worked_minutes=r.worked_minutes if r else 0, late_minutes=r.late_minutes if r else 0, status=status_,
                                 record_id=r.id if r else None, presence=loc.live_status(db, e)["presence"]))
    db.commit()
    return rows


@router.get("/attendance/dashboard/", response_model=DashboardOut)
def dashboard(day_param: date | None = Query(default=None, alias="date"), department_id: int | None = None,
              p: Principal = Depends(require_viewer), db: Session = Depends(get_db)):
    now = utcnow()
    today = _org_today(db, p)
    day = day_param or today
    is_today = day == today
    settings = att.org_settings(db, p.org_id)
    q = scope_employees(select(Employee), p).where(Employee.is_active.is_(True))
    if department_id:
        q = q.where(Employee.department_id == department_id)
    emps = db.scalars(q).unique().all()
    c = dict(scheduled=0, present=0, late=0, missing=0, inside=0, outside=0, unconfirmed=0, unavailable=0, leave=0, absent=0, worked=0, overtime=0,
             stale=0, active=0, away=0)
    for e in emps:
        shift = (shift_for_instant(db, e, now, settings) if is_today else None) or shift_for_date(db, e, day, settings)
        view = presence_service.resolve(db, e, now, settings=settings) if is_today else None
        if view is not None:
            c["inside"] += view.zone_status == "INSIDE"
            c["outside"] += view.zone_status == "OUTSIDE"
            c["stale"] += view.zone_status == "STALE"
            c["active"] += view.session_status == "ACTIVE"
            c["away"] += view.session_status == "TEMPORARY_EXIT"
        if shift is None:
            continue
        c["scheduled"] += 1
        r = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == e.id, AttendanceRecord.work_date == shift.work_date))
        st = r.status if r else None
        if st in (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.HALF_DAY, AttendanceStatus.INCOMPLETE):
            c["present"] += 1
        if r and r.late_minutes > 0:
            c["late"] += 1
        if r and st in (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.HALF_DAY, AttendanceStatus.INCOMPLETE):
            if r.sessions and not r.is_finalized:
                att.recompute(db, r, now)
            c["worked"] += r.worked_minutes
            c["overtime"] += r.overtime_minutes
        if st == AttendanceStatus.ABSENT and r.is_finalized:
            c["absent"] += 1
        if st == AttendanceStatus.PENDING_CONFIRMATION or (r and any(s.confirmation == SessionConfirmation.PENDING for s in r.sessions)):
            c["unconfirmed"] += 1
        on_leave = st == AttendanceStatus.ON_LEAVE or (r is None and att.has_leave(db, e.id, shift.start, shift.end))
        if on_leave:
            c["leave"] += 1
        has_session = bool(r and any(s.confirmation != SessionConfirmation.REJECTED for s in r.sessions))
        if not has_session and not on_leave and now > shift.start + timedelta(minutes=shift.grace_period_minutes) and not (r and r.is_finalized):
            c["missing"] += 1
            if view is None or view.zone_status in ("STALE", "UNKNOWN", "LOCATION_DENIED", "NO_OFFICE") or not view.consent_granted:
                c["unavailable"] += 1
    emp_ids = [e.id for e in emps]
    db.commit()
    return DashboardOut(
        absent=c["absent"] + c["missing"] - c["unavailable"],  # finalized absences + no check-in despite a location signal
        avg_working_minutes=round(c["worked"] / c["present"]) if c["present"] else 0, overtime_minutes=c["overtime"], is_today=is_today,
        stale=c["stale"], active_sessions=c["active"], temporary_exits=c["away"],
        date=day, total_employees=len(emps), scheduled_today=c["scheduled"], present=c["present"], late=c["late"], missing_check_ins=c["missing"],
        inside_office=c["inside"], outside_office=c["outside"], unconfirmed=c["unconfirmed"], location_unavailable=c["unavailable"], on_leave=c["leave"],
        open_anomalies=db.scalar(select(func.count()).select_from(AttendanceAnomaly).where(AttendanceAnomaly.organization_id == p.org_id, AttendanceAnomaly.status == AnomalyStatus.OPEN,
                                                                                           AttendanceAnomaly.employee_id.in_(emp_ids or [-1]))) or 0,
        pending_corrections=db.scalar(select(func.count()).select_from(AttendanceCorrection).where(AttendanceCorrection.organization_id == p.org_id,
                                                                                                    AttendanceCorrection.status == RequestStatus.PENDING,
                                                                                                    AttendanceCorrection.employee_id.in_(emp_ids or [-1]))) or 0,
    )


@router.get("/attendance/", response_model=Page[RecordOut])
def list_records(date_from: date | None = None, date_to: date | None = None, employee_id: int | None = None, department_id: int | None = None,
                 office_id: int | None = None, status_: AttendanceStatus | None = Query(default=None, alias="status"), pg: tuple[int, int] = Depends(pagination),
                 p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    page, size = pg
    q = scope_employees(select(AttendanceRecord).join(Employee, Employee.id == AttendanceRecord.employee_id), p).where(AttendanceRecord.organization_id == p.org_id)
    if date_from:
        q = q.where(AttendanceRecord.work_date >= date_from)
    if date_to:
        q = q.where(AttendanceRecord.work_date <= date_to)
    if employee_id:
        q = q.where(AttendanceRecord.employee_id == employee_id)
    if department_id:
        q = q.where(Employee.department_id == department_id)
    if office_id:
        q = q.where(AttendanceRecord.office_id == office_id)
    if status_:
        q = q.where(AttendanceRecord.status == status_)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.order_by(AttendanceRecord.work_date.desc(), Employee.full_name).offset((page - 1) * size).limit(size)).all()
    return Page(items=[_record_out(db, r) for r in items], total=total or 0, page=page, page_size=size)


@router.get("/attendance/corrections/", response_model=list[CorrectionOut])
def list_corrections(status_filter: RequestStatus | None = Query(default=None, alias="status"), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = scope_employees(select(AttendanceCorrection, Employee.full_name, AttendanceRecord.work_date)
                        .join(Employee, Employee.id == AttendanceCorrection.employee_id)
                        .join(AttendanceRecord, AttendanceRecord.id == AttendanceCorrection.record_id), p)
    if status_filter:
        q = q.where(AttendanceCorrection.status == status_filter)
    out = []
    for c, name, wd in db.execute(q.order_by(AttendanceCorrection.created_at.desc()).limit(500)).all():
        o = CorrectionOut.model_validate(c)
        o.employee_name, o.work_date = name, wd
        out.append(o)
    return out


@router.post("/attendance/corrections/{correction_id}/review/", response_model=CorrectionOut)
def review_correction(correction_id: int, body: ReviewIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    c = db.get(AttendanceCorrection, correction_id)
    if c is None or c.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correction not found")
    emp = get_employee_or_404(db, p, c.employee_id)
    if p.employee and emp.id == p.employee.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot review your own correction")
    if c.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reviewed")
    now = utcnow()
    if body.approve:
        try:
            att.apply_correction(db, c, p.user, now)
        except att.AttendanceError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    c.status = RequestStatus.APPROVED if body.approve else RequestStatus.REJECTED
    c.reviewed_by_id, c.reviewed_at, c.review_comment = p.user.id, now, body.comment
    audit(db, org_id=p.org_id, actor_id=p.user.id, action=f"correction.{c.status.value.lower()}", entity_type="attendance_correction", entity_id=c.id,
          changes={"comment": body.comment})
    notify_employee(db, emp, type="CORRECTION_REVIEWED", title=f"Correction {c.status.value.lower()}",
                    body=body.comment or f"Your correction request was {c.status.value.lower()}.", data={"record_id": c.record_id, "correction_id": c.id})
    db.commit()
    return CorrectionOut.model_validate(c)


@router.get("/attendance/{record_id}/", response_model=RecordDetailOut)
def get_record(record_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    r = _get_record(db, p, record_id)
    if not r.is_finalized:
        att.recompute(db, r, utcnow())
        db.commit()
    return _record_out(db, r, detail=True)


@router.post("/attendance/{record_id}/approve/", response_model=RecordDetailOut)
def approve_record(record_id: int, body: ApprovalIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    r = _get_record(db, p, record_id)
    emp = db.get(Employee, r.employee_id)
    if not can_review_employee(p, emp):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot approve your own attendance")
    loc.lock_employee(db, r.employee_id)
    try:
        att.approve(db, r, p.user, approve_=body.approve, session_id=body.session_id, now=utcnow())
    except att.AttendanceError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.commit()
    return _record_out(db, r, detail=True)


@router.post("/attendance/{record_id}/dispute/", response_model=CorrectionOut, status_code=201)
def dispute(record_id: int, body: DisputeIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Employee disputes an automatically recorded attendance. Totals change only after a reviewer approves."""
    r = _get_record(db, p, record_id)
    if p.employee is None or r.employee_id != p.employee.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the employee can dispute their own attendance")
    return request_correction(record_id, CorrectionIn(type=CorrectionType.DISPUTE, reason=body.reason, requested_check_in=body.requested_check_in,
                                                      requested_check_out=body.requested_check_out), p, db)


@router.post("/attendance/{record_id}/confirm/", response_model=RecordDetailOut)
def confirm(record_id: int, body: ConfirmIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    r = _get_record(db, p, record_id)
    if p.employee is None or r.employee_id != p.employee.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the employee can confirm their own attendance")
    pending_arrival = any(s.confirmation == SessionConfirmation.PENDING for s in r.sessions)
    if pending_arrival and att.org_settings(db, p.org_id).confirmation_policy == ConfirmationPolicy.MANAGER_APPROVAL and body.action == "CONFIRM" \
            and not any(s.status == SessionStatus.PENDING_CHECKOUT for s in r.sessions):
        raise HTTPException(status.HTTP_409_CONFLICT, "Attendance in this organization is approved by a manager")
    loc.lock_employee(db, r.employee_id)  # serialize with GPS processing
    try:
        att.confirm(db, r, p.user, action=body.action, session_id=body.session_id, now=utcnow())
    except att.AttendanceError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND if exc.code == "not_found" else status.HTTP_409_CONFLICT, str(exc)) from None
    db.commit()
    return _record_out(db, r, detail=True)


@router.post("/attendance/{record_id}/correction/", response_model=CorrectionOut, status_code=201)
def request_correction(record_id: int, body: CorrectionIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    r = _get_record(db, p, record_id)
    if not (p.employee and r.employee_id == p.employee.id) and not p.is_hr:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the employee or HR can request a correction")
    if db.scalar(select(AttendanceCorrection.id).where(AttendanceCorrection.record_id == r.id, AttendanceCorrection.status == RequestStatus.PENDING)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A correction for this day is already pending")
    c = AttendanceCorrection(organization_id=p.org_id, record_id=r.id, employee_id=r.employee_id, requested_by_id=p.user.id, **body.model_dump())
    db.add(c)
    db.flush()
    emp = db.get(Employee, r.employee_id)
    audit(db, org_id=p.org_id, actor_id=p.user.id, action="correction.requested", entity_type="attendance_correction", entity_id=c.id, changes=body.model_dump())
    notify_hr(db, p.org_id, emp.department_id if emp else None, type="CORRECTION_REQUESTED", title="Attendance correction requested",
              body=f"{emp.full_name if emp else 'An employee'} requested a correction for {r.work_date.isoformat()}.", data={"correction_id": c.id, "record_id": r.id})
    db.commit()
    return CorrectionOut.model_validate(c)


@router.post("/attendance/manual-record/", response_model=RecordDetailOut, status_code=201)
def manual_record(employee_id: int, work_date: date, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """HR helper: materialise a record for a scheduled day (e.g. LOCATION_UNAVAILABLE) so a correction can be filed against it."""
    emp = get_employee_or_404(db, p, employee_id)
    settings = att.org_settings(db, p.org_id)
    shift = shift_for_date(db, emp, work_date, settings)
    if shift is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Employee is not scheduled on this date")
    r = att.get_or_create_record(db, emp, shift)
    att.recompute(db, r, utcnow())
    db.commit()
    return _record_out(db, r, detail=True)


# --------------------------------------------------------------- anomalies ----

@router.get("/anomalies/", response_model=list[AnomalyOut])
def list_anomalies(status_filter: AnomalyStatus | None = Query(default=AnomalyStatus.OPEN, alias="status"), p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    q = scope_employees(select(AttendanceAnomaly, Employee.full_name).join(Employee, Employee.id == AttendanceAnomaly.employee_id), p)
    if status_filter:
        q = q.where(AttendanceAnomaly.status == status_filter)
    out = []
    for a, name in db.execute(q.order_by(AttendanceAnomaly.detected_at.desc()).limit(500)).all():
        o = AnomalyOut.model_validate(a)
        o.employee_name = name
        out.append(o)
    return out


@router.post("/anomalies/{anomaly_id}/review/", response_model=AnomalyOut)
def review_anomaly(anomaly_id: int, body: AnomalyReviewIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    a = db.get(AttendanceAnomaly, anomaly_id)
    if a is None or a.organization_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anomaly not found")
    get_employee_or_404(db, p, a.employee_id)
    a.status = AnomalyStatus(body.status)
    a.reviewed_by_id, a.reviewed_at, a.review_comment = p.user.id, utcnow(), body.comment
    audit(db, org_id=p.org_id, actor_id=p.user.id, action=f"anomaly.{body.status.lower()}", entity_type="attendance_anomaly", entity_id=a.id, changes={"comment": body.comment})
    db.commit()
    return AnomalyOut.model_validate(a)


# ----------------------------------------------------------- notifications ----

@router.get("/notifications/", response_model=list[NotificationOut])
def my_notifications(unread: bool = False, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == p.user.id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    return db.scalars(q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100)).all()


@router.post("/notifications/{notification_id}/read/", status_code=204)
def mark_read(notification_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != p.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    n.read_at = n.read_at or utcnow()
    db.commit()
