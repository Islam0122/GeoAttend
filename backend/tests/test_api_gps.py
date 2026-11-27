"""GPS ingestion through the HTTP API."""
from datetime import timedelta

from sqlalchemy import func, select

from app.models import AttendanceAnomaly, AttendanceSession, LocationEvent
from tests.conftest import MONDAY, local, offset


def test_inside_radius_creates_attendance(world):
    e = world.employee()
    r = world.arrive(e, local(MONDAY, 8, 55))
    body = r.json()
    assert r.status_code == 201 and body["zone"] == "INSIDE" and body["transition"] == "ENTER"
    assert body["distance_m"] < 1 and body["attendance_status"] == "PRESENT"
    assert world.today(e, local(MONDAY, 8, 57))["location"]["presence"] == "INSIDE"   # last validated reading 08:56
    t = world.today(e, local(MONDAY, 10))
    assert t["record"]["actual_check_in"].startswith("2026-11-23T02:55")  # arrival = first reading of the streak (08:55 local)
    # 64 min without a location check: presence is STALE, but the work session is untouched
    assert t["location"]["presence"] == "STALE" and t["location"]["session_state"] == "ACTIVE"


def test_outside_radius_no_attendance(world):
    e = world.employee()
    r = world.stream(e, local(MONDAY, 8, 55), offset(500))
    assert r.json()["zone"] == "OUTSIDE" and r.json()["transition"] is None
    assert world.today(e, local(MONDAY, 10))["record"] is None


def test_uncertain_accuracy_never_confirms(world):
    e = world.employee()
    # 95 m away with 10 m accuracy -> straddles the 100 m boundary
    r = world.stream(e, local(MONDAY, 8, 55), offset(95), n=5)
    assert r.json()["zone"] == "UNCERTAIN" and r.json()["transition"] is None
    # good position but accuracy (80 m) worse than the geofence max (50 m)
    r = world.stream(e, local(MONDAY, 9, 0), offset(0), n=5, accuracy=80)
    assert r.json()["result"] == "LOW_ACCURACY" and r.json()["zone"] == "UNCERTAIN"
    assert world.today(e, local(MONDAY, 10))["record"] is None
    # monitoring endpoint lists them, without coordinates
    rows = world.get("/locations/uncertain/").json()
    assert rows and "latitude" not in rows[0]


def test_invalid_coordinates_rejected(world):
    e = world.employee()
    for lat, lng, acc, reason in [(95, 10, 10, "COORDINATES_OUT_OF_RANGE"), (0, 0, 10, "NULL_ISLAND"), (42.87, 74.56, -1, "INVALID_ACCURACY"), (42.87, 74.56, 5000, "ACCURACY_UNREASONABLE")]:
        r = world.send(e, local(MONDAY, 9), (lat, lng), accuracy=acc)
        assert r.status_code == 422 and r.json()["detail"]["code"] == reason
    # schema-level garbage
    assert world.c.post("/api/v1/locations/events/", json={"latitude": "abc"}, headers=e.headers).status_code == 422


def test_future_and_too_old_timestamps(world):
    e = world.employee()
    at = local(MONDAY, 9)
    assert world.send(e, at, offset(0), now=at - timedelta(minutes=10)).json()["detail"]["code"] == "FUTURE_TIMESTAMP"
    assert world.send(e, at, offset(0), now=at + timedelta(days=5)).json()["detail"]["code"] == "EVENT_TOO_OLD"


def test_never_trusts_client_distance_or_status(world, db):
    e = world.employee()
    r = world.send(e, local(MONDAY, 9), offset(900), distance_m=0, zone="INSIDE", attendance_status="PRESENT", inside=True)
    assert r.status_code == 201 and r.json()["zone"] == "OUTSIDE" and r.json()["distance_m"] > 850


def test_duplicate_events_are_idempotent(world, db):
    e = world.employee()
    fix = world.fix(e, local(MONDAY, 9), offset(0))
    from tests.conftest import freeze
    freeze(local(MONDAY, 9, 1))
    r1 = world.c.post("/api/v1/locations/events/", json=fix, headers=e.headers)
    r2 = world.c.post("/api/v1/locations/events/", json=fix, headers=e.headers)
    assert r1.status_code == 201 and r2.status_code == 200 and r2.json()["result"] == "DUPLICATE"
    assert r1.json()["event_id"] == r2.json()["event_id"]
    # same device + same timestamp under a new id is also a duplicate (client retry bug)
    fix2 = {**fix, "client_event_id": "another-id-123"}
    assert world.c.post("/api/v1/locations/events/", json=fix2, headers=e.headers).json()["result"] == "DUPLICATE"
    assert db.scalar(select(func.count()).select_from(LocationEvent)) == 1


def test_mock_location_is_flagged_not_counted(world, db):
    e = world.employee()
    for i in range(4):
        r = world.send(e, local(MONDAY, 9) + timedelta(seconds=30 * i), offset(0), is_mocked=True)
        assert r.json()["result"] == "SUSPICIOUS"
    assert world.today(e, local(MONDAY, 10))["record"] is None
    a = db.scalars(select(AttendanceAnomaly)).all()
    assert {x.type.value for x in a} == {"MOCK_LOCATION"}
    assert world.get("/anomalies/").json()[0]["severity"] == "HIGH"


def test_impossible_jump_is_suspicious(world, db):
    e = world.employee()
    world.send(e, local(MONDAY, 8, 50), offset(20_000))         # 20 km away
    r = world.send(e, local(MONDAY, 8, 50, 30), offset(0))      # 30 s later at the office
    assert r.json()["result"] == "SUSPICIOUS" and r.json()["reason"] == "IMPOSSIBLE_SPEED"
    assert db.scalar(select(AttendanceAnomaly.type)).value == "IMPOSSIBLE_SPEED"


def test_unstable_transitions_do_not_create_sessions(world, db):
    e = world.employee()
    t = local(MONDAY, 8, 50)
    for i in range(8):  # alternate inside/outside every 30 s
        world.send(e, t + timedelta(seconds=30 * i), offset(0 if i % 2 else 400))
    assert db.scalar(select(func.count()).select_from(AttendanceSession)) == 0


def test_two_readings_are_not_enough(world, db):
    e = world.employee()
    world.stream(e, local(MONDAY, 8, 50), offset(0), n=2)
    assert db.scalar(select(func.count()).select_from(AttendanceSession)) == 0
    world.send(e, local(MONDAY, 8, 51), offset(0))
    assert db.scalar(select(func.count()).select_from(AttendanceSession)) == 1


def test_consent_required(world):
    e = world.employee(consent=False)
    r = world.send(e, local(MONDAY, 9), offset(0))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CONSENT_REQUIRED"
    # withdrawn consent stops processing
    e2 = world.employee()
    world.post("/consent/", {"granted": False, "consent_version": "1.0"}, actor=e2, expect=201)
    assert world.send(e2, local(MONDAY, 9), offset(0)).status_code == 403


def test_unregistered_device_rejected(world):
    e = world.employee(device=False)
    r = world.send(e, local(MONDAY, 9), offset(0))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "DEVICE_NOT_REGISTERED"


def test_shared_device_blocked(world):
    a = world.employee()
    b = world.employee(device=False)
    r = world.post("/devices/register/", {"device_id": a.device_id, "platform": "IOS"}, actor=b)
    assert r.status_code == 409
    assert any(x["type"] == "SHARED_DEVICE" for x in world.get("/anomalies/").json())


def test_no_tracking_outside_working_window(world, db):
    e = world.employee()
    # 02:00 local, 6 h before the window opens; Saturday is a day off
    assert world.send(e, local(MONDAY, 2), offset(0)).json()["detail"]["code"] == "OUTSIDE_TRACKING_WINDOW"
    assert world.send(e, local(MONDAY + timedelta(days=5), 10), offset(0)).json()["detail"]["code"] == "OUTSIDE_TRACKING_WINDOW"
    assert db.scalar(select(func.count()).select_from(LocationEvent)) == 0  # coordinates not stored


def test_status_endpoint_exposes_window_and_fences(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 8, 55))
    from tests.conftest import freeze
    freeze(local(MONDAY, 8, 57))
    s = world.get("/locations/me/status/", actor=e).json()
    assert s["tracking_active"] and s["consent_granted"] and s["presence"] == "INSIDE"
    assert s["offices"][0]["radius_m"] == 100 and s["tracking_window"]["start"].startswith("2026-11-23T02:00")
    freeze(local(MONDAY, 23, 0))
    assert world.get("/locations/me/status/", actor=e).json()["tracking_active"] is False


def test_history_is_private_to_employee(world):
    a, b = world.employee(), world.employee()
    world.send(a, local(MONDAY, 9), offset(0))
    assert world.get("/locations/me/history/", actor=a).json()["total"] == 1
    assert world.get("/locations/me/history/", actor=b).json()["total"] == 0
    mon = world.get("/locations/monitoring/").json()
    assert all("latitude" not in row for row in mon)


def test_batch_offline_sync_out_of_order_and_bad_items(world):
    e = world.employee()
    t = local(MONDAY, 8, 57)
    fixes = [world.fix(e, t + timedelta(seconds=30 * i), offset(0)) for i in range(4)]
    batch = list(reversed(fixes)) + [{"client_event_id": "x", "latitude": 1}] + [world.fix(e, t, (200, 1))]
    from tests.conftest import freeze
    freeze(local(MONDAY, 11))  # synced 2 hours later
    r = world.post("/locations/batch/", {"events": batch}, actor=e)
    body = r.json()
    assert r.status_code == 200 and body["accepted"] == 4 and body["rejected"] == 2
    rec = world.today(e, local(MONDAY, 11))["record"]
    assert rec["actual_check_in"].startswith("2026-11-23T02:57")  # true arrival, not sync time
    # replaying the whole batch is idempotent
    r2 = world.post("/locations/batch/", {"events": fixes}, actor=e).json()
    assert r2["duplicates"] == 4 and r2["accepted"] == 0


def test_out_of_order_single_event_is_not_applied(world):
    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    r = world.send(e, local(MONDAY, 8, 30), offset(800), now=local(MONDAY, 9, 5))
    assert r.json()["result"] == "OUT_OF_ORDER"
    loc_now = world.today(e, local(MONDAY, 9, 2))["location"]
    assert loc_now["presence"] == "INSIDE" and loc_now["validated_zone"] == "INSIDE"  # 08:30 OUTSIDE reading was not applied
    later = world.today(e, local(MONDAY, 9, 6))["location"]
    assert later["presence"] == "STALE" and later["validated_zone"] == "INSIDE"  # last valid check 09:01 > 2 min ago
