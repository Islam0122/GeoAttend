"""Schedule resolution: overnight, DST, precedence."""
from datetime import date, datetime, time, timezone

from app.models import (
    Department,
    Employee,
    Organization,
    OrganizationSettings,
    ScheduleAssignment,
    ScheduleDay,
    User,
    WorkSchedule,
)
from app.services.schedule_service import shift_for_date, shift_for_instant


def _setup(db, tz="Europe/Berlin"):
    org = Organization(name="X", slug="x", timezone=tz)
    db.add(org)
    db.flush()
    s = OrganizationSettings(organization_id=org.id)
    dept = Department(organization_id=org.id, name="D")
    u = User(organization_id=org.id, email="x@x.test", full_name="X")
    db.add_all([s, dept, u])
    db.flush()
    emp = Employee(organization_id=org.id, user_id=u.id, employee_code="1", full_name="X", department_id=dept.id)
    db.add(emp)
    db.flush()
    return org, s, dept, emp


def _schedule(db, org, name, start, end, weekdays=range(7)):
    ws = WorkSchedule(organization_id=org.id, name=name)
    ws.days = [ScheduleDay(weekday=d, start_time=start, end_time=end) for d in weekdays]
    db.add(ws)
    db.flush()
    return ws


def test_overnight_shift(db):
    org, s, dept, emp = _setup(db, "UTC")
    ws = _schedule(db, org, "Night", time(22), time(6))
    db.add(ScheduleAssignment(organization_id=org.id, schedule_id=ws.id, employee_id=emp.id, effective_from=date(2026, 1, 1)))
    db.flush()
    sh = shift_for_date(db, emp, date(2026, 11, 23), s)
    assert sh.start == datetime(2026, 11, 23, 22, tzinfo=timezone.utc) and sh.end == datetime(2026, 11, 24, 6, tzinfo=timezone.utc)
    # 03:00 on the 24th belongs to the 23rd's shift
    inst = shift_for_instant(db, emp, datetime(2026, 11, 24, 3, tzinfo=timezone.utc), s)
    assert inst.work_date == date(2026, 11, 23)
    assert sh.scheduled_minutes == 480


def test_dst_transition(db):
    org, s, dept, emp = _setup(db, "Europe/Berlin")
    ws = _schedule(db, org, "Day", time(9), time(17))
    db.add(ScheduleAssignment(organization_id=org.id, schedule_id=ws.id, employee_id=emp.id, effective_from=date(2026, 1, 1)))
    db.flush()
    before = shift_for_date(db, emp, date(2026, 3, 27), s)  # CET (UTC+1)
    after = shift_for_date(db, emp, date(2026, 3, 30), s)   # CEST (UTC+2)
    assert before.start.hour == 8 and after.start.hour == 7


def test_employee_assignment_overrides_department(db):
    org, s, dept, emp = _setup(db, "UTC")
    dept_ws = _schedule(db, org, "Dept", time(8), time(16))
    own_ws = _schedule(db, org, "Own", time(10), time(18))
    db.add(ScheduleAssignment(organization_id=org.id, schedule_id=dept_ws.id, department_id=dept.id, effective_from=date(2026, 1, 1)))
    db.flush()
    assert shift_for_date(db, emp, date(2026, 11, 23), s).start.hour == 8
    db.add(ScheduleAssignment(organization_id=org.id, schedule_id=own_ws.id, employee_id=emp.id, effective_from=date(2026, 11, 1)))
    db.flush()
    assert shift_for_date(db, emp, date(2026, 11, 23), s).start.hour == 10
    assert shift_for_date(db, emp, date(2026, 10, 20), s).start.hour == 8  # before own assignment


def test_day_off_has_no_shift(db):
    org, s, dept, emp = _setup(db, "UTC")
    ws = _schedule(db, org, "Weekdays", time(9), time(17), weekdays=range(5))
    db.add(ScheduleAssignment(organization_id=org.id, schedule_id=ws.id, employee_id=emp.id, effective_from=date(2026, 1, 1)))
    db.flush()
    assert shift_for_date(db, emp, date(2026, 11, 28), s) is None  # Saturday
