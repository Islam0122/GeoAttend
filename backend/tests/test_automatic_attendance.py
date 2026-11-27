"""Automatic Attendance Mode — end-to-end through the HTTP API (presence checks every 30 s).

Scenario numbers refer to the specification (1-35). Shift: 09:00-18:00, grace 0, lunch 13:00-14:00.
Policy defaults: entry 2 readings, exit 3 readings, stale 120 s, temporary-exit grace 10 min,
maximum absence 30 min, checkout grace 15 min, automatic closure timeout 120 min.
"""
import json
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import AttendanceSession, GeofenceTransition, LocationEvent
from app.services import automation
from tests.conftest import MONDAY, OFFICE, World, freeze, local, offset

TUESDAY = MONDAY + timedelta(days=1)
SUNDAY = MONDAY + timedelta(days=6)
IN, FAR = offset(10), offset(600)


@pytest.fixture
def w(client) -> World:
    freeze(local(MONDAY, 6))
    world = World(client, "AutoCo", auto_geofence=False)
    world.settings(attendance_mode="AUTOMATIC")
    strict = world.post("/schedules/", {"name": "Strict", "grace_period_minutes": 0, "days": [
        {"weekday": d, "start_time": "09:00", "end_time": "18:00", "break_start": "13:00", "break_end": "14:00"} for d in range(5)]}, expect=201).json()
    world.strict = strict
    return world


def emp(w: World, **kw):
    a = w.employee(schedule=False, **kw)
    w.post("/schedules/assign/", {"schedule_id": w.strict["id"], "employee_id": a.employee_id, "effective_from": "2026-01-01"}, expect=201)
    return a


def pc(w: World, a, at, lat_lng, accuracy=10.0, now=None, event_uuid=None, expect=200):
    freeze(now or at + timedelta(seconds=1))
    body = {"event_uuid": event_uuid or uuid.uuid4().hex, "device_id": a.device_id, "latitude": lat_lng[0], "longitude": lat_lng[1],
            "accuracy": accuracy, "timestamp": at.isoformat()}
    r = w.c.post("/api/v1/attendance/presence-check/", json=body, headers=a.headers)
    assert r.status_code == expect, r.text
    return r.json()


def stream(w, a, start, lat_lng, n, accuracy=10.0):
    out = None
    for i in range(n):
        out = pc(w, a, start + timedelta(seconds=30 * i), lat_lng, accuracy)
    return out


def today(w, a, at):
    freeze(at)
    return w.get("/attendance/automatic/today/", actor=a).json()


def effects(db_emp_id=None):
    with SessionLocal() as s:
        q = select(GeofenceTransition.attendance_effect).order_by(GeofenceTransition.id)
        if db_emp_id:
            q = q.where(GeofenceTransition.employee_id == db_emp_id)
        return [e for e in s.scalars(q) if e]


# ---------------------------------------------------------------- basic 1-10 ----

def test_full_automatic_day(w):
    """1-10: open screen, inside -> auto check-in, exit -> temporary exit, return -> resumed, final checkout."""
    a = emp(w)
    first = pc(w, a, local(MONDAY, 8, 50), IN)
    assert first["ui_state"] == "INSIDE_GEOFENCE" and "1/2" in first["message"]
    assert first["presence"]["zone_status"] == "INSIDE" and first["reading"]["distance_m"] < 15
    second = pc(w, a, local(MONDAY, 8, 50, 30), IN)
    assert second["ui_state"] == "AUTO_CHECKIN" and second["presence"]["session_status"] == "ACTIVE"
    assert second["presence"]["check_in_time"].startswith("2026-11-23T02:50")  # 08:50 local = first reading of the streak

    t = today(w, a, local(MONDAY, 9))
    s = t["record"]["sessions"][0]
    assert s["detection_method"] == "AUTOMATIC" and s["check_in_accuracy_m"] == 10 and s["check_in_device_id"] == a.device_id
    assert t["record"]["status"] == "PRESENT" and t["record"]["early_arrival_minutes"] == 10  # scenario 29

    # 5-6: two outside readings are not enough (3 required); session stays ACTIVE
    r = stream(w, a, local(MONDAY, 11), FAR, 2)
    assert r["ui_state"] == "ACTIVE_SESSION" and "2/3" in r["message"]
    r = pc(w, a, local(MONDAY, 11, 1), FAR)
    assert r["ui_state"] == "TEMPORARY_EXIT" and r["presence"]["session_status"] == "TEMPORARY_EXIT"
    # 7-8: return (2 readings) resumes the same session
    pc(w, a, local(MONDAY, 11, 20), IN)
    r = pc(w, a, local(MONDAY, 11, 20, 30), IN)
    assert r["ui_state"] == "SESSION_RESUMED"
    t = today(w, a, local(MONDAY, 12))
    sess = t["record"]["sessions"]
    assert len(sess) == 1 and sess[0]["status"] == "OPEN"
    ex = sess[0]["temporary_exits"][0]
    assert ex["exited_at"].startswith("2026-11-23T05:00") and ex["returned_at"].startswith("2026-11-23T05:20")
    assert ex["duration_minutes"] == 20 and ex["counted_as_working_time"] is False and ex["detection_method"] == "AUTOMATIC"
    # 9: 08:50-12:00 = 190 min, minus 20 min away = 170 payable; presence also 170
    assert t["record"]["worked_minutes"] == 170 and t["record"]["temporary_exit_minutes"] == 20 and t["record"]["presence_minutes"] == 170

    # 10: leaving after 17:45 (shift end - 15 min checkout grace) is the final checkout
    stream(w, a, local(MONDAY, 17, 50), FAR, 3)
    t = today(w, a, local(MONDAY, 18))
    assert t["ui_state"] == "SESSION_COMPLETED" and t["presence"]["session_status"] == "COMPLETED"
    assert t["record"]["sessions"][0]["close_reason"] == "GEOFENCE_EXIT" and t["record"]["early_departure_minutes"] == 10
    assert effects(a.employee_id) == ["AUTO_CHECKIN", "TEMPORARY_EXIT", "RETURN_TO_OFFICE", "FINAL_CHECKOUT"]


def test_counting_policy_and_grace(w):
    """Count temporary exits as working time ON vs OFF; short exits within grace are always counted."""
    a, b = emp(w), emp(w)
    stream(w, a, local(MONDAY, 9), IN, 2)
    stream(w, a, local(MONDAY, 10), FAR, 3)
    stream(w, a, local(MONDAY, 10, 8), IN, 2)  # away 08 min (< 10 min grace)
    stream(w, a, local(MONDAY, 11), FAR, 3)
    stream(w, a, local(MONDAY, 11, 25), IN, 2)  # away 25 min
    t = today(w, a, local(MONDAY, 12))
    exits = t["record"]["sessions"][0]["temporary_exits"]
    assert [x["counted_as_working_time"] for x in exits] == [True, False]
    assert t["record"]["worked_minutes"] == 180 - 25 and t["record"]["temporary_exit_minutes"] == 33 and t["record"]["presence_minutes"] == 180 - 33

    w.settings(count_temporary_exit_as_work=True)
    stream(w, b, local(MONDAY, 9), IN, 2)
    stream(w, b, local(MONDAY, 11), FAR, 3)
    stream(w, b, local(MONDAY, 11, 25), IN, 2)
    tb = today(w, b, local(MONDAY, 12))
    assert tb["record"]["worked_minutes"] == 180 and tb["record"]["presence_minutes"] == 155  # payable vs physical presence kept apart


# ------------------------------------------------------------ errors 11-25 ----

def test_permission_denied(w):
    """11"""
    a = emp(w)
    stream(w, a, local(MONDAY, 9), IN, 2)
    freeze(local(MONDAY, 9, 5))
    w.post("/devices/heartbeat/", {"device_id": a.device_id, "location_permission": "DENIED"}, actor=a, expect=200)
    st = w.get("/attendance/automatic/status/", actor=a).json()
    assert st["presence"]["zone_status"] == "LOCATION_DENIED" and st["presence"]["session_status"] == "ACTIVE"  # session kept
    row = w.get("/monitoring/employees/").json()[0]
    assert row["zone_status"] == "LOCATION_DENIED" and row["permission"] == "DENIED"


def test_inaccurate_gps_never_changes_state(w):
    """12"""
    a = emp(w)
    for i in range(6):
        r = pc(w, a, local(MONDAY, 9) + timedelta(seconds=30 * i), IN, accuracy=80)
        assert r["ui_state"] == "GPS_INACCURATE"
    assert r["presence"]["zone_status"] == "LOCATION_DETECTED" and r["presence"]["session_status"] == "NOT_STARTED"
    stream(w, a, local(MONDAY, 9, 5), IN, 2)  # good readings -> check-in
    r = stream(w, a, local(MONDAY, 10), FAR, 5, accuracy=120)  # inaccurate "outside" readings
    assert r["presence"]["session_status"] == "ACTIVE" and r["presence"]["validated_zone"] == "INSIDE" and r["ui_state"] == "ACTIVE_SESSION"


def test_outside_all_offices(w):
    """13"""
    a = emp(w)
    r = stream(w, a, local(MONDAY, 9), FAR, 4)
    assert r["ui_state"] == "OUTSIDE_GEOFENCE" and r["presence"]["session_status"] == "NOT_STARTED" and r["reading"]["distance_m"] > 550


def test_no_assigned_office(w):
    """14"""
    a = emp(w, offices=[])
    r = pc(w, a, local(MONDAY, 9), IN)
    assert r["ui_state"] == "NO_OFFICE" and r["presence"]["zone_status"] == "NO_OFFICE"
    assert w.get("/monitoring/employees/", params={"filter": "no_office"}).json()[0]["employee_id"] == a.employee_id


def test_no_shift_unscheduled_policy(w):
    """15: no shift -> nothing recorded unless unscheduled attendance is allowed."""
    a = emp(w)
    r = pc(w, a, local(SUNDAY, 11), IN)
    assert r["ui_state"] == "UNSCHEDULED" and "not allowed" in r["message"]
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(LocationEvent)) == 0  # privacy: no coordinates stored outside the window
    w.settings(allow_unscheduled_attendance=True)
    pc(w, a, local(SUNDAY, 11, 1), IN)
    r = pc(w, a, local(SUNDAY, 11, 1, 30), IN)
    assert r["ui_state"] == "AUTO_CHECKIN"
    t = today(w, a, local(SUNDAY, 12))
    assert t["record"]["status"] == "UNSCHEDULED" and t["record"]["is_unscheduled"] and t["ui_state"] == "UNSCHEDULED"
    assert t["record"]["late_minutes"] == 0 and t["record"]["worked_minutes"] == 59


def test_lost_signal_keeps_session_and_becomes_stale(w):
    """16-19: offline / tab closed / background / GPS stopped: no fake checkout; STALE after 2 min."""
    a = emp(w)
    stream(w, a, local(MONDAY, 9), IN, 2)
    freeze(local(MONDAY, 9, 1, 30))
    assert w.get("/attendance/automatic/status/", actor=a).json()["presence"]["zone_status"] == "INSIDE"
    freeze(local(MONDAY, 9, 3))
    st = w.get("/attendance/automatic/status/", actor=a).json()
    assert st["ui_state"] == "ACTIVE_SESSION" and st["presence"]["zone_status"] == "STALE"
    for at in (local(MONDAY, 12), local(MONDAY, 17)):  # jobs during the shift never close the session
        freeze(at)
        with SessionLocal() as s:
            automation.resolve_sessions(s, at)
            assert automation.detect_stale_presence(s, at) in (0, 1)
    st = w.get("/attendance/automatic/status/", actor=a).json()
    assert st["presence"]["session_status"] == "ACTIVE"
    assert [x["type"] for x in w.get("/anomalies/").json()] == ["LOCATION_STALE"]  # informational, once per day


def test_duplicate_and_repeated_operations(w):
    """20-22"""
    a = emp(w)
    uid = uuid.uuid4().hex
    pc(w, a, local(MONDAY, 9), IN, event_uuid=uid)
    pc(w, a, local(MONDAY, 9), IN, event_uuid=uid, now=local(MONDAY, 9, 0, 10))  # resend
    pc(w, a, local(MONDAY, 9, 0, 30), IN)
    stream(w, a, local(MONDAY, 9, 1), IN, 6)  # 21: more inside readings, no new check-in
    stream(w, a, local(MONDAY, 10), FAR, 3)
    stream(w, a, local(MONDAY, 10, 2), FAR, 6)  # 22: more outside readings, no extra exit
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(LocationEvent).where(LocationEvent.client_event_id == uid)) == 1
        assert s.scalar(select(func.count()).select_from(AttendanceSession)) == 1
    t = today(w, a, local(MONDAY, 10, 10))
    assert len(t["record"]["sessions"][0]["temporary_exits"]) == 1
    assert effects(a.employee_id) == ["AUTO_CHECKIN", "TEMPORARY_EXIT"]
    # 21: manual check-in is rejected in Automatic mode
    freeze(local(MONDAY, 10, 11))
    r = w.c.post("/api/v1/attendance/manual-check-in/", json={"event_uuid": uuid.uuid4().hex, "device_id": a.device_id, "latitude": IN[0],
                                                             "longitude": IN[1], "accuracy": 10, "recorded_at": local(MONDAY, 10, 11).isoformat()}, headers=a.headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MANUAL_DISABLED"


def test_parallel_presence_checks_single_session(w):
    """23"""
    a = emp(w)
    pc(w, a, local(MONDAY, 9), IN)
    freeze(local(MONDAY, 9, 1))
    bodies = [{"event_uuid": uuid.uuid4().hex, "device_id": a.device_id, "latitude": IN[0], "longitude": IN[1], "accuracy": 10,
               "timestamp": (local(MONDAY, 9, 0, 30) + timedelta(seconds=i)).isoformat()} for i in range(6)]
    codes = []
    threads = [threading.Thread(target=lambda b=b: codes.append(w.c.post("/api/v1/attendance/presence-check/", json=b, headers=a.headers).status_code)) for b in bodies]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert set(codes) == {200}
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(AttendanceSession).where(AttendanceSession.status.in_(["OPEN", "AWAY"]))) == 1


def test_blocked_employee(w):
    """24"""
    a = emp(w)
    assert w.c.delete(f"/api/v1/employees/{a.employee_id}/", headers=w.admin.headers).status_code == 204
    freeze(local(MONDAY, 9, 1))
    r = w.c.post("/api/v1/attendance/presence-check/", json={"event_uuid": uuid.uuid4().hex, "device_id": a.device_id, "latitude": IN[0],
                                                            "longitude": IN[1], "accuracy": 10, "timestamp": local(MONDAY, 9).isoformat()}, headers=a.headers)
    assert r.status_code == 401


def test_manager_cannot_obtain_coordinates(w):
    """25: monitoring exposes zone/distance/accuracy only; no endpoint returns another employee's coordinates."""
    mgr = emp(w, role="MANAGER", managed=[w.dept["id"]])
    a = emp(w)
    other = emp(w, department=w.dept2)
    stream(w, a, local(MONDAY, 9), IN, 2)
    stream(w, other, local(MONDAY, 9), IN, 2)
    freeze(local(MONDAY, 9, 1, 30))
    rows = w.get("/monitoring/employees/", actor=mgr).json()
    raw = json.dumps(rows)
    assert "latitude" not in raw and "longitude" not in raw and str(round(IN[0], 4)) not in raw
    assert {r["employee_id"] for r in rows} == {mgr.employee_id, a.employee_id}  # department scoping
    assert w.get("/locations/me/history/", actor=mgr).json()["total"] == 0  # own history only
    assert w.get("/locations/monitoring/", actor=a).status_code == 403
    assert w.get(f"/attendance/sessions/?employee_id={other.employee_id}", actor=mgr).json()["total"] == 0


# ------------------------------------------------------------- edge 26-35 ----

def test_multiple_and_overlapping_offices(w, db):
    """26-27: overlapping geofences -> one session at the primary office; switching offices keeps one session."""
    overlap = w.post("/offices/", {"name": "AI Hub", "latitude": OFFICE[0] + 0.0004, "longitude": OFFICE[1], "radius": 150}, expect=201).json()  # 45 m away
    far = w.post("/offices/", {"name": "FullCode Academy", "latitude": OFFICE[0] + 0.045, "longitude": OFFICE[1]}, expect=201).json()
    a = emp(w, offices=[w.office["id"], overlap["id"], far["id"]])
    stream(w, a, local(MONDAY, 9), IN, 2)  # inside HQ and AI Hub
    t = today(w, a, local(MONDAY, 9, 2))
    assert len(t["record"]["sessions"]) == 1 and t["record"]["sessions"][0]["office_id"] == w.office["id"]
    assert sorted(effects(a.employee_id)) == ["AUTO_CHECKIN", "IGNORED_OVERLAP"]
    stream(w, a, local(MONDAY, 12), offset(600), 3)  # walk to FullCode Academy
    stream(w, a, local(MONDAY, 12, 20), (far["latitude"], far["longitude"]), 2)
    t = today(w, a, local(MONDAY, 12, 30))
    assert len(t["record"]["sessions"]) == 1 and t["record"]["sessions"][0]["office_id"] == far["id"]


def test_overnight_shift_automatic(w):
    """28"""
    night = w.post("/schedules/", {"name": "Night", "grace_period_minutes": 0, "days": [{"weekday": d, "start_time": "22:00", "end_time": "06:00"} for d in range(7)]}, expect=201).json()
    a = w.employee(schedule=False)
    w.post("/schedules/assign/", {"schedule_id": night["id"], "employee_id": a.employee_id, "effective_from": "2026-01-01"}, expect=201)
    stream(w, a, local(MONDAY, 22, 5), IN, 2)
    stream(w, a, local(TUESDAY, 6, 0), FAR, 3)  # >= 06:00 - 15 min grace -> final checkout
    t = today(w, a, local(TUESDAY, 6, 5))
    assert t["record"]["work_date"] == "2026-11-23" and t["record"]["late_minutes"] == 5 and t["record"]["worked_minutes"] == 475
    assert t["record"]["sessions"][0]["close_reason"] == "GEOFENCE_EXIT"


def test_late_arrival_and_early_departure(w):
    """30-31: 09:15 -> LATE 15; leaving 17:30 -> early departure 30 (after the maximum absence elapses)."""
    a = emp(w)
    stream(w, a, local(MONDAY, 9, 15), IN, 2)
    t = today(w, a, local(MONDAY, 9, 20))
    assert t["record"]["status"] == "LATE" and t["record"]["late_minutes"] == 15
    stream(w, a, local(MONDAY, 17, 30), FAR, 3)  # before 17:45 -> temporary exit, not the end of the day
    assert today(w, a, local(MONDAY, 17, 35))["presence"]["session_status"] == "TEMPORARY_EXIT"
    freeze(local(MONDAY, 18, 5))
    with SessionLocal() as s:
        automation.resolve_sessions(s, local(MONDAY, 18, 5))  # 30 min maximum absence exceeded
    t = today(w, a, local(MONDAY, 18, 6))
    assert t["record"]["early_departure_minutes"] == 30 and t["record"]["actual_check_out"].startswith("2026-11-23T11:30")
    assert t["record"]["sessions"][0]["temporary_exits"][0]["outcome"] == "NOT_RETURNED"  # exit kept, not deleted


def test_return_after_long_absence_starts_new_session(w):
    """33"""
    a = emp(w)
    stream(w, a, local(MONDAY, 9), IN, 2)
    stream(w, a, local(MONDAY, 10), FAR, 3)
    stream(w, a, local(MONDAY, 11), IN, 2)  # away 60 min > 30 min maximum absence
    t = today(w, a, local(MONDAY, 11, 5))
    s1, s2 = t["record"]["sessions"]
    assert s1["ended_at"].startswith("2026-11-23T04:00") and s1["temporary_exits"][0]["outcome"] == "NOT_RETURNED"
    assert s2["status"] == "OPEN" and s2["detection_method"] == "AUTOMATIC" and t["record"]["worked_minutes"] == 60 + 5


def test_shift_end_with_browser_open(w):
    """34: still inside after the shift -> session kept; closed by the timeout at the last validated inside time."""
    a = emp(w)
    stream(w, a, local(MONDAY, 9), IN, 2)
    stream(w, a, local(MONDAY, 18, 30), IN, 4)  # browser still open, employee still inside
    freeze(local(MONDAY, 19))
    with SessionLocal() as s:
        automation.resolve_sessions(s, local(MONDAY, 19))
    assert today(w, a, local(MONDAY, 19, 1))["presence"]["session_status"] == "ACTIVE"
    freeze(local(MONDAY, 20, 1))
    with SessionLocal() as s:
        automation.resolve_sessions(s, local(MONDAY, 20, 1))  # 18:00 + 120 min timeout
    t = today(w, a, local(MONDAY, 20, 2))
    s = t["record"]["sessions"][0]
    assert s["status"] == "PENDING_CHECKOUT" and s["ended_at"].startswith("2026-11-23T12:31") and t["record"]["overtime_minutes"] == 91  # 571 worked (no lunch taken) - 480 scheduled


def test_stale_measurement_is_not_replayed(w):
    """35"""
    a = emp(w)
    r = pc(w, a, local(MONDAY, 9), IN, now=local(MONDAY, 9, 5))
    assert r["reading"]["reason"] == "STALE_MEASUREMENT" and r["presence"]["zone_status"] == "UNKNOWN"
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(LocationEvent)) == 0


# --------------------------------------------------- modes, policy, overrides ----

def test_manual_mode_presence_only_and_hybrid(w):
    w.settings(attendance_mode="MANUAL")
    a = emp(w)
    r = stream(w, a, local(MONDAY, 9), IN, 3)
    assert r["ui_state"] == "INSIDE_GEOFENCE" and "Check in" in r["message"] and r["presence"]["session_status"] == "NOT_STARTED"
    assert effects(a.employee_id) == ["PRESENCE_ONLY"]
    w.settings(attendance_mode="HYBRID")
    b = emp(w)
    stream(w, b, local(MONDAY, 9, 5), IN, 2)
    assert today(w, b, local(MONDAY, 9, 7))["presence"]["session_status"] == "ACTIVE"
    freeze(local(MONDAY, 12))
    r = w.c.post("/api/v1/attendance/manual-check-out/", json={"event_uuid": uuid.uuid4().hex, "device_id": b.device_id, "latitude": IN[0],
                                                              "longitude": IN[1], "accuracy": 10, "recorded_at": local(MONDAY, 12).isoformat()}, headers=b.headers)
    assert r.status_code == 201 and r.json()["state"] == "CHECK_OUT_SUCCESS"


def test_policy_disables(w):
    a = emp(w)
    w.patch("/attendance/policy/", {"automatic_checkin_enabled": False})
    r = stream(w, a, local(MONDAY, 9), IN, 3)
    assert r["presence"]["session_status"] == "NOT_STARTED" and "disabled" in r["message"]
    w.patch("/attendance/policy/", {"automatic_checkin_enabled": True, "automatic_checkout_enabled": False})
    b = emp(w)
    stream(w, b, local(MONDAY, 9, 5), IN, 2)
    r = stream(w, b, local(MONDAY, 10), FAR, 4)
    assert r["presence"]["session_status"] == "ACTIVE"  # exit not acted on
    w.patch("/attendance/policy/", {"automatic_detection_enabled": False})
    freeze(local(MONDAY, 10, 5))
    r = w.c.post("/api/v1/attendance/presence-check/", json={"event_uuid": uuid.uuid4().hex, "device_id": b.device_id, "latitude": IN[0],
                                                            "longitude": IN[1], "accuracy": 10, "timestamp": local(MONDAY, 10, 5).isoformat()}, headers=b.headers)
    assert r.status_code == 409


def test_policy_api_and_audit(w):
    p = w.get("/attendance/policy/").json()
    assert p["attendance_mode"] == "AUTOMATIC" and p["entry_confirmation_count"] == 2 and p["exit_confirmation_count"] == 3
    assert p["presence_interval_seconds"] == 30 and p["presence_stale_seconds"] == 120 and p["temporary_exit_grace_minutes"] == 10
    a = emp(w)
    assert w.patch("/attendance/policy/", {"exit_confirmation_count": 4}, actor=a).status_code == 403
    assert w.patch("/attendance/policy/", {"entry_confirmation_count": 0}).status_code == 422
    w.patch("/attendance/policy/", {"exit_confirmation_count": 4})
    assert any(l["action"] == "policy.updated" for l in w.get("/audit-logs/").json()["items"])
    assert w.get("/attendance/policy/", actor=a).json()["exit_confirmation_count"] == 4  # employees can read the policy


def test_admin_override_audited_and_dispute(w):
    a = emp(w)
    mgr = emp(w, role="MANAGER", managed=[w.dept["id"]])
    stream(w, a, local(MONDAY, 9, 20), IN, 2)
    sid = today(w, a, local(MONDAY, 10))["record"]["sessions"][0]["id"]
    assert w.patch(f"/attendance/sessions/{sid}/", {"check_in_at": local(MONDAY, 9).isoformat(), "reason": "GPS delayed"}, actor=mgr).status_code == 403
    assert w.patch(f"/attendance/sessions/{sid}/", {"check_in_at": local(MONDAY, 9).isoformat()}).status_code == 422  # reason required
    r = w.patch(f"/attendance/sessions/{sid}/", {"check_in_at": local(MONDAY, 9).isoformat(), "check_out_at": local(MONDAY, 18).isoformat(), "reason": "Badge log confirms"})
    assert r.status_code == 200 and r.json()["detection_method"] == "CORRECTION"
    entry = next(l for l in w.get("/audit-logs/").json()["items"] if l["action"] == "attendance.session_override")
    assert entry["changes"]["reason"] == "Badge log confirms" and "old" in entry["changes"]["changes"]["check_in_at"]
    t = today(w, a, local(MONDAY, 18, 5))
    assert t["record"]["late_minutes"] == 0 and t["record"]["worked_minutes"] == 540
    rid = t["record"]["id"]
    assert w.post(f"/attendance/{rid}/dispute/", {"reason": "I left at 17:00"}, actor=a).status_code == 201


def test_monitoring_filters_and_summary(w):
    a, b, c = emp(w), emp(w), emp(w, offices=[])
    stream(w, a, local(MONDAY, 9, 20), IN, 2)
    stream(w, b, local(MONDAY, 9), IN, 2)
    stream(w, b, local(MONDAY, 10, 30), FAR, 3)
    freeze(local(MONDAY, 10, 32))
    s = w.get("/monitoring/summary/").json()
    assert s["total_employees"] == 3 and s["temporary_exits"] == 1 and s["active_sessions"] == 1 and s["late_today"] == 1
    assert s["currently_outside"] == 1 and s["no_office"] == 1 and s["stale"] == 1
    late = w.get("/monitoring/employees/", params={"filter": "late"}).json()
    assert [r["employee_id"] for r in late] == [a.employee_id] and late[0]["late_minutes"] == 20 and late[0]["working_minutes"] == 72
    row = w.get("/monitoring/employees/", params={"filter": "temporary_exit"}).json()[0]
    assert row["employee_id"] == b.employee_id and row["zone_status"] == "OUTSIDE" and row["temporary_exit_started_at"]
    assert w.get("/monitoring/employees/", params={"filter": "nope"}).status_code == 422
    assert c.employee_id in [r["employee_id"] for r in w.get("/monitoring/employees/", params={"filter": "no_office"}).json()]


def test_reports_include_automatic_metrics(w):
    a = emp(w)
    stream(w, a, local(MONDAY, 8, 50), IN, 2)
    stream(w, a, local(MONDAY, 11), FAR, 3)
    stream(w, a, local(MONDAY, 11, 20), IN, 2)
    stream(w, a, local(MONDAY, 17, 50), FAR, 3)
    freeze(local(MONDAY, 21))
    row = w.get("/reports/daily/", params={"date": "2026-11-23"}).json()["rows"][0]
    assert row["early_arrival_minutes"] == 10 and row["temporary_exit_minutes"] == 20
    assert row["total_presence_minutes"] == 540 - 20 and row["payable_minutes"] == 540 - 20 and row["early_departure_minutes"] == 10
    m = w.get("/reports/monthly/", params={"month": "2026-11-01"}).json()["rows"][0]
    assert m["present_days"] == 1 and m["temporary_exit_minutes"] == 20 and m["attendance_percentage"] == 100.0


def test_every_presence_and_session_status(w):
    """Each zone status (UNKNOWN, LOCATION_DETECTED, INSIDE, OUTSIDE, STALE, LOCATION_DENIED, NO_OFFICE) and
    session status (NOT_STARTED, ACTIVE, TEMPORARY_EXIT, COMPLETED) is produced by real server data."""
    a, nobody = emp(w), emp(w, offices=[])

    def st(at):
        freeze(at)
        return w.get("/attendance/automatic/status/", actor=a).json()["presence"]

    assert (st(local(MONDAY, 8, 55))["zone_status"], st(local(MONDAY, 8, 55))["session_status"]) == ("UNKNOWN", "NOT_STARTED")
    pc(w, a, local(MONDAY, 9), IN, accuracy=90)
    assert st(local(MONDAY, 9, 0, 5))["zone_status"] == "LOCATION_DETECTED"
    stream(w, a, local(MONDAY, 9, 1), IN, 2)
    p = st(local(MONDAY, 9, 1, 40))
    assert (p["zone_status"], p["session_status"]) == ("INSIDE", "ACTIVE") and p["distance_m"] is not None and p["accuracy_m"] == 10
    stream(w, a, local(MONDAY, 10), FAR, 3)
    p = st(local(MONDAY, 10, 1, 10))
    assert (p["zone_status"], p["session_status"]) == ("OUTSIDE", "TEMPORARY_EXIT")
    assert st(local(MONDAY, 10, 4))["zone_status"] == "STALE"
    freeze(local(MONDAY, 10, 4))
    w.post("/devices/heartbeat/", {"device_id": a.device_id, "location_permission": "DENIED"}, actor=a, expect=200)
    assert st(local(MONDAY, 10, 4))["zone_status"] == "LOCATION_DENIED"
    w.post("/devices/heartbeat/", {"device_id": a.device_id, "location_permission": "GRANTED_WHEN_IN_USE"}, actor=a, expect=200)
    stream(w, a, local(MONDAY, 10, 5), IN, 2)
    stream(w, a, local(MONDAY, 17, 50), FAR, 3)
    assert st(local(MONDAY, 17, 51, 10))["session_status"] == "COMPLETED"
    freeze(local(MONDAY, 17, 52))
    assert w.get("/attendance/automatic/status/", actor=nobody).json()["presence"]["zone_status"] == "NO_OFFICE"
