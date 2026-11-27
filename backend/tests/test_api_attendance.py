"""Hybrid attendance scenarios end-to-end through the API + automation jobs."""
from datetime import timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AttendanceAnomaly, Notification
from app.services import automation
from tests.conftest import MONDAY, OFFICE, freeze, local, offset

TUESDAY = MONDAY + timedelta(days=1)


def run_job(fn, at):
    freeze(at)
    with SessionLocal() as s:
        return fn(s, at)


def rec(world, e, at):
    return world.today(e, at)["record"]


def test_on_time_arrival(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9, 5))  # within 10 min grace
    r = rec(world, e, local(MONDAY, 12))
    assert r["status"] == "PRESENT" and r["late_minutes"] == 0
    assert r["worked_minutes"] == 175  # live working time 09:05 -> 12:00
    assert r["scheduled_start"].startswith("2026-11-23T03:00")


def test_late_arrival_and_notification(world, db):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9, 25))
    r = rec(world, e, local(MONDAY, 10))
    assert r["status"] == "LATE" and r["late_minutes"] == 15  # 09:25 - 09:00 - 10 grace
    n = db.scalars(select(Notification).where(Notification.user_id == e.user_id, Notification.type == "CHECK_IN")).one()
    assert "15 min late" in n.body


def test_lunch_break_keeps_session(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 13, 5))
    t = world.today(e, local(MONDAY, 13, 20))
    assert t["record"]["sessions"][0]["status"] == "AWAY" and t["record"]["sessions"][0]["breaks"][0]["type"] == "LUNCH"
    world.arrive(e, local(MONDAY, 13, 50))
    world.leave(e, local(MONDAY, 18, 5))
    r = rec(world, e, local(MONDAY, 19))
    assert len(r["sessions"]) == 1 and r["sessions"][0]["status"] == "CLOSED"
    assert r["break_minutes"] == 45
    assert r["worked_minutes"] == 9 * 60 + 5 - 45  # 500
    assert r["overtime_minutes"] == 20 and r["early_departure_minutes"] == 0 and r["status"] == "PRESENT"


def test_temporary_exit_short_errand(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 11))
    world.arrive(e, local(MONDAY, 11, 20))
    r = rec(world, e, local(MONDAY, 12))
    assert len(r["sessions"]) == 1 and r["sessions"][0]["status"] == "OPEN"
    assert r["break_minutes"] == 20 and r["worked_minutes"] == 160


def test_temporary_exit_counted_as_work_when_policy_says_so(world):
    world.settings(count_temporary_exit_as_work=True)
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 11))
    world.arrive(e, local(MONDAY, 11, 20))
    r = rec(world, e, local(MONDAY, 12))
    assert r["break_minutes"] == 0 and r["worked_minutes"] == 180


def test_long_exit_creates_multiple_sessions(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 11))
    world.arrive(e, local(MONDAY, 12))  # 60 min > 30 min temporary-exit limit
    r = rec(world, e, local(MONDAY, 12, 30))
    assert len(r["sessions"]) == 2
    first, second = r["sessions"]
    assert first["status"] == "CLOSED" and first["close_reason"] == "TEMPORARY_EXIT_EXPIRED"
    assert first["check_out_at"].startswith("2026-11-23T05:00")  # 11:00 local
    assert second["status"] == "OPEN" and r["worked_minutes"] == 120 + 30


def test_early_departure_resolved_by_job(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 16))
    # Not closed immediately: could be an errand.
    assert rec(world, e, local(MONDAY, 16, 10))["sessions"][0]["status"] == "AWAY"
    run_job(automation.resolve_sessions, local(MONDAY, 16, 40))
    r = rec(world, e, local(MONDAY, 16, 45))
    s = r["sessions"][0]
    assert s["status"] == "CLOSED" and s["check_out_at"].startswith("2026-11-23T10:00")
    assert r["early_departure_minutes"] == 120 and r["worked_minutes"] == 420 and r["actual_check_out"].startswith("2026-11-23T10:00")


def test_exit_after_shift_end_closes_immediately(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 8, 50))
    world.leave(e, local(MONDAY, 18, 2))
    r = rec(world, e, local(MONDAY, 18, 10))
    assert r["sessions"][0]["status"] == "CLOSED" and r["sessions"][0]["close_reason"] == "GEOFENCE_EXIT"
    assert r["worked_minutes"] == 552 and r["overtime_minutes"] == 72


def test_overnight_shift(world):
    night = world.post("/schedules/", {"name": "Night", "grace_period_minutes": 5,
                                        "days": [{"weekday": d, "start_time": "22:00", "end_time": "06:00"} for d in range(7)]}, expect=201).json()
    e = world.employee(schedule=False)
    world.post("/schedules/assignments/", {"schedule_id": night["id"], "employee_id": e.employee_id, "effective_from": "2026-01-01"}, expect=201)
    world.arrive(e, local(MONDAY, 22, 12))
    world.leave(e, local(TUESDAY, 6, 10))
    freeze(local(TUESDAY, 7))
    recs = world.get("/attendance/", actor=e).json()["items"]
    assert len(recs) == 1 and recs[0]["work_date"] == "2026-11-23"
    assert recs[0]["late_minutes"] == 7 and recs[0]["worked_minutes"] == 7 * 60 + 58 and recs[0]["status"] == "LATE"


def test_missing_gps_is_location_unavailable_not_absent(world, db):
    e = world.employee()
    assert run_job(automation.detect_missing_checkins, local(MONDAY, 9, 30)) == 1
    assert run_job(automation.detect_missing_checkins, local(MONDAY, 9, 45)) == 0  # notified once
    assert db.scalar(select(Notification.type).where(Notification.user_id == e.user_id, Notification.type == "MISSING_CHECK_IN"))
    run_job(automation.finalize_days, local(TUESDAY, 0, 30))
    freeze(local(TUESDAY, 1))
    r = world.get("/attendance/", actor=e).json()["items"][0]
    assert r["status"] == "LOCATION_UNAVAILABLE" and r["is_finalized"]
    types = {a.type.value for a in db.scalars(select(AttendanceAnomaly))}
    assert {"MISSING_CHECK_IN", "LOCATION_UNAVAILABLE"} <= types


def test_absent_only_with_location_signal(world):
    e = world.employee()
    world.stream(e, local(MONDAY, 10), offset(3000))  # phone works, employee never came
    run_job(automation.finalize_days, local(TUESDAY, 0, 30))
    freeze(local(TUESDAY, 1))
    assert world.get("/attendance/", actor=e).json()["items"][0]["status"] == "ABSENT"


def test_incomplete_when_tracking_window_ends(world, db):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.send(e, local(MONDAY, 15), offset(5))  # last fix, then phone dies
    run_job(automation.resolve_sessions, local(MONDAY, 20, 5))  # window ends 18:00 + 120 min
    run_job(automation.finalize_days, local(MONDAY, 20, 10))
    freeze(local(MONDAY, 21))
    r = world.get("/attendance/", actor=e).json()["items"][0]
    assert r["status"] == "INCOMPLETE" and r["actual_check_out"].startswith("2026-11-23T09:00")  # provisional, needs confirmation
    detail = world.get(f"/attendance/{r['id']}/", actor=e).json()
    assert detail["pending_checkout"] and detail["sessions"][0]["check_out_at"].startswith("2026-11-23T09:00")  # 15:00 local
    assert db.scalar(select(AttendanceAnomaly.type).where(AttendanceAnomaly.type == "INCOMPLETE_SESSION"))
    # employee confirms the suggested checkout
    out = world.post(f"/attendance/{r['id']}/confirm/", {"action": "CONFIRM"}, actor=e, expect=200).json()
    assert out["sessions"][0]["status"] == "CLOSED" and out["status"] == "PRESENT" and out["early_departure_minutes"] == 180


def test_employee_confirmation_policy(world, db):
    world.settings(confirmation_policy="EMPLOYEE_CONFIRMATION")
    e = world.employee()
    world.arrive(e, local(MONDAY, 9, 20))
    t = world.today(e, local(MONDAY, 9, 40))["record"]
    assert t["status"] == "PENDING_CONFIRMATION" and t["pending_confirmation"] and t["worked_minutes"] == 0
    assert db.scalar(select(Notification.type).where(Notification.user_id == e.user_id, Notification.type == "CONFIRM_ARRIVAL"))
    # reminder job
    assert run_job(automation.remind_pending_confirmations, local(MONDAY, 10, 30)) == 1
    freeze(local(MONDAY, 10, 35))
    out = world.post(f"/attendance/{t['id']}/confirm/", {"action": "CONFIRM"}, actor=e, expect=200).json()
    s = out["sessions"][0]
    assert out["status"] == "LATE" and out["late_minutes"] == 10
    assert s["confirmation"] == "CONFIRMED" and s["detected_at"].startswith("2026-11-23T03:21") and s["confirmed_at"].startswith("2026-11-23T04:35")
    assert world.post(f"/attendance/{t['id']}/confirm/", {"action": "CONFIRM"}, actor=e).status_code == 409


def test_employee_can_reject_detection(world):
    world.settings(confirmation_policy="EMPLOYEE_CONFIRMATION")
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    rid = world.today(e, local(MONDAY, 9, 5))["record"]["id"]
    out = world.post(f"/attendance/{rid}/confirm/", {"action": "REJECT"}, actor=e, expect=200).json()
    assert out["sessions"][0]["confirmation"] == "REJECTED" and out["worked_minutes"] == 0


def test_checkout_requires_confirmation_policy(world):
    world.settings(checkout_policy="REQUIRE_CONFIRMATION")
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 18, 1))
    r = world.today(e, local(MONDAY, 18, 10))["record"]
    assert r["pending_checkout"] and r["sessions"][0]["status"] == "PENDING_CHECKOUT"
    out = world.post(f"/attendance/{r['id']}/confirm/", {}, actor=e, expect=200).json()
    assert out["sessions"][0]["status"] == "CLOSED" and out["sessions"][0]["checkout_confirmed_at"]


def test_business_trip_counts_as_work(world):
    e = world.employee()
    world.post("/leave-requests/", {"employee_id": e.employee_id, "type": "BUSINESS_TRIP", "starts_at": local(MONDAY, 11).isoformat(),
                              "ends_at": local(MONDAY, 15).isoformat(), "reason": "Client visit"}, expect=201)
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 11, 5))
    assert world.today(e, local(MONDAY, 12))["record"]["sessions"][0]["breaks"][0]["type"] == "BUSINESS_TRIP"
    run_job(automation.resolve_sessions, local(MONDAY, 15, 5))
    r = rec(world, e, local(MONDAY, 15, 10))
    assert r["sessions"][0]["close_reason"] == "BUSINESS_TRIP_END" and r["worked_minutes"] == 360 and r["break_minutes"] == 0


def test_on_leave(world):
    e = world.employee()
    world.post("/leave-requests/", {"employee_id": e.employee_id, "type": "LEAVE", "starts_at": local(MONDAY, 0).isoformat(),
                              "ends_at": local(TUESDAY, 0).isoformat()}, expect=201)
    assert run_job(automation.detect_missing_checkins, local(MONDAY, 9, 30)) == 0
    run_job(automation.finalize_days, local(TUESDAY, 0, 30))
    freeze(local(TUESDAY, 1))
    assert world.get("/attendance/", actor=e).json()["items"][0]["status"] == "ON_LEAVE"


def test_employee_leave_request_needs_approval(world):
    e = world.employee()
    a = world.post("/leave-requests/", {"type": "LEAVE", "starts_at": local(MONDAY, 0).isoformat(), "ends_at": local(TUESDAY, 0).isoformat()}, actor=e, expect=201).json()
    assert a["status"] == "PENDING"
    assert world.post(f"/leave-requests/{a['id']}/review/", {"approve": True}, actor=e).status_code == 403
    assert world.post(f"/leave-requests/{a['id']}/review/", {"approve": True}, expect=200).json()["status"] == "APPROVED"


def test_manual_correction_flow(world):
    e = world.employee()
    run_job(automation.finalize_days, local(TUESDAY, 0, 30))
    freeze(local(TUESDAY, 9))
    rid = world.get("/attendance/", actor=e).json()["items"][0]["id"]
    body = {"type": "MISSING_CHECK_IN", "requested_check_in": local(MONDAY, 9).isoformat(), "requested_check_out": local(MONDAY, 18).isoformat(),
            "reason": "Phone battery died"}
    c = world.post(f"/attendance/{rid}/correction/", body, actor=e, expect=201).json()
    assert world.post(f"/attendance/{rid}/correction/", body, actor=e).status_code == 409  # one pending at a time
    assert world.post(f"/attendance/corrections/{c['id']}/review/", {"approve": True}, actor=e).status_code == 403  # not staff
    out = world.post(f"/attendance/corrections/{c['id']}/review/", {"approve": True, "comment": "Verified with badge log"}, expect=200).json()
    assert out["status"] == "APPROVED"
    r = world.get(f"/attendance/{rid}/", actor=e).json()
    assert r["status"] == "PRESENT" and r["worked_minutes"] == 480 and r["break_minutes"] == 60
    assert r["sessions"][0]["source"] == "CORRECTION"
    logs = world.get("/audit-logs/").json()["items"]
    assert any(l["action"] == "attendance.correction_applied" for l in logs)


def test_dispute_automatic_attendance(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 18, 5))
    freeze(local(MONDAY, 19))
    rid = world.get("/attendance/", actor=e).json()["items"][0]["id"]
    c = world.post(f"/attendance/{rid}/correction/", {"type": "WRONG_TIME", "requested_check_in": local(MONDAY, 8, 40).isoformat(),
                                                       "reason": "I arrived earlier, GPS was slow"}, actor=e, expect=201).json()
    world.post(f"/attendance/corrections/{c['id']}/review/", {"approve": True}, expect=200)
    r = world.get(f"/attendance/{rid}/", actor=e).json()
    assert r["actual_check_in"].startswith("2026-11-23T02:40")


def test_multiple_offices_switch(world, db):
    """Moving between two assigned offices keeps ONE session; the switch is recorded as an event."""
    from app.models import GeofenceTransition

    branch = world.post("/offices/", {"name": "Branch", "latitude": OFFICE[0] + 0.045, "longitude": OFFICE[1]}, expect=201).json()  # ~5 km
    e = world.employee(offices=[world.office["id"], branch["id"]])
    world.arrive(e, local(MONDAY, 9))
    world.leave(e, local(MONDAY, 11, 50))
    world.stream(e, local(MONDAY, 12, 10), (branch["latitude"], branch["longitude"]))
    r = rec(world, e, local(MONDAY, 13))
    assert len(r["sessions"]) == 1 and r["sessions"][0]["office_id"] == branch["id"] and r["sessions"][0]["status"] == "OPEN"
    assert r["sessions"][0]["breaks"][0]["type"] == "TEMPORARY_EXIT"  # travel time kept as an exit interval
    effects = [t.attendance_effect for t in db.scalars(select(GeofenceTransition).order_by(GeofenceTransition.id))]
    assert effects == ["AUTO_CHECKIN", "TEMPORARY_EXIT", "RETURN_TO_OFFICE"]
    assert db.scalars(select(GeofenceTransition).order_by(GeofenceTransition.id.desc())).first().note == "office switch"

def test_dashboard_and_team_today(world):
    on_time, late, _missing = world.employee("Ann"), world.employee("Bob"), world.employee("Cat")
    world.arrive(on_time, local(MONDAY, 8, 50))
    world.arrive(late, local(MONDAY, 9, 40))
    freeze(local(MONDAY, 10))
    d = world.get("/attendance/dashboard/").json()
    assert d["scheduled_today"] == 3 and d["present"] == 2 and d["late"] == 1 and d["missing_check_ins"] == 1
    assert d["inside_office"] == 0 and d["stale"] == 2 and d["location_unavailable"] == 1  # nobody re-checked since arrival
    freeze(local(MONDAY, 9, 42))
    assert world.get("/attendance/dashboard/").json()["inside_office"] == 1  # Bob's arrival readings are fresh
    freeze(local(MONDAY, 10))
    rows = {r["employee_name"]: r for r in world.get("/attendance/today/team/").json()}
    assert rows["Cat"]["status"] == "NOT_CHECKED_IN" and rows["Bob"]["late_minutes"] == 30
    assert rows["Ann"]["presence"] == "STALE"  # last check 08:51; now 10:00 -> stale, never "inside" from old data


def test_reports(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9, 30))
    world.leave(e, local(MONDAY, 16))
    run_job(automation.resolve_sessions, local(MONDAY, 17))
    freeze(local(MONDAY, 21))
    daily = world.get("/reports/daily/", params={"date": "2026-11-23"}).json()
    assert daily["rows"][0]["late_minutes"] == 20 and daily["rows"][0]["early_departure_minutes"] == 120
    weekly = world.get("/reports/weekly/", params={"week_of": "2026-11-25"}).json()
    assert weekly["start"] == "2026-11-23" and weekly["rows"][0]["late_days"] == 1
    monthly = world.get("/reports/monthly/", params={"month": "2026-11-01"}).json()
    assert monthly["end"] == "2026-11-30" and monthly["totals"]["late_minutes"] == 20
    late = world.get("/reports/late-arrivals/", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    early = world.get("/reports/early-leaves/", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert late["count"] == 1 and late["rows"][0]["minutes"] == 20 and early["rows"][0]["minutes"] == 120
    csv = world.get("/reports/daily/", params={"date": "2026-11-23", "format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and "employee_name" in csv.text
    # snapshots job is idempotent
    from app.models.enums import ReportType
    with SessionLocal() as s:
        assert automation.generate_reports(s, local(TUESDAY, 1), ReportType.DAILY) == 1
        assert automation.generate_reports(s, local(TUESDAY, 2), ReportType.DAILY) == 0
    assert world.get("/reports/snapshots/").json()[0]["period_start"] == "2026-11-23"
