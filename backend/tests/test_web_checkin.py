"""Web/PWA explicit attendance workflow + auth/billing/report additions."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.db import SessionLocal, engine
from app.integrations import google_oauth
from app.models import AttendanceAnomaly, LocationEvent
from app.services import automation, geo
from tests.conftest import MONDAY, OFFICE, World, freeze, local, offset

TUESDAY = MONDAY + timedelta(days=1)


@pytest.fixture
def web(client):
    freeze(local(MONDAY, 6))
    return World(client, "Webco", auto_geofence=False)


def gps(w: World, a, at, lat_lng, accuracy=12.0, event_uuid=None, now=None, path="/attendance/check-in/"):
    freeze(now or at + timedelta(seconds=1))
    body = {"event_uuid": event_uuid or uuid.uuid4().hex, "device_id": a.device_id, "latitude": lat_lng[0], "longitude": lat_lng[1],
            "accuracy": accuracy, "recorded_at": at.isoformat()}
    return w.c.post(f"/api/v1{path}", json=body, headers=a.headers)


def out(w, a, at, lat_lng=None, **kw):
    return gps(w, a, at, lat_lng or offset(900), path="/attendance/check-out/", **kw)


def test_check_in_success_and_late_example(web):
    """Spec example: schedule 09:00-18:00, grace 5, arrival 09:13 -> 8 late minutes."""
    sched = web.post("/schedules/", {"name": "Grace5", "grace_period_minutes": 5,
                                     "days": [{"weekday": d, "start_time": "09:00", "end_time": "18:00"} for d in range(5)]}, expect=201).json()
    e = web.employee(schedule=False)
    web.post("/schedules/assign/", {"schedule_id": sched["id"], "employee_id": e.employee_id, "effective_from": "2026-01-01"}, expect=201)
    r = gps(web, e, local(MONDAY, 9, 13), offset(35))
    body = r.json()
    assert r.status_code == 201 and body["state"] == "CHECK_IN_SUCCESS"
    assert 30 < body["distance_m"] < 40 and body["radius_m"] == 100 and body["office_name"] == "HQ" and body["zone"] == "INSIDE"
    t = web.today(e, local(MONDAY, 9, 30))
    assert t["record"]["late_minutes"] == 8 and t["record"]["status"] == "LATE"
    assert t["actions"]["can_check_out"] and not t["actions"]["can_check_in"]
    assert t["offices"][0]["radius_m"] == 100


@pytest.mark.parametrize("north,accuracy,state,code", [
    (95, 10, "GPS_ACCURACY_LOW", "GEOFENCE_BOUNDARY"),   # 95+10 > 100, 95-10 <= 100
    (20, 75, "GPS_ACCURACY_LOW", "GPS_ACCURACY_LOW"),    # accuracy worse than 50 m office maximum
    (300, 10, "OUTSIDE_GEOFENCE", "OUTSIDE_GEOFENCE"),
])
def test_check_in_rejections(web, north, accuracy, state, code):
    e = web.employee()
    r = gps(web, e, local(MONDAY, 8, 55), offset(north), accuracy=accuracy)
    assert r.status_code == 422 and r.json()["state"] == state and r.json()["code"] == code
    assert web.today(e, local(MONDAY, 9))["record"] is None


def test_geofence_boundary_exact(web):
    e = web.employee()
    assert gps(web, e, local(MONDAY, 8, 55), offset(89.5), accuracy=10).status_code == 201  # 99.5 <= 100


def test_check_in_idempotent_and_already_checked_in(web, db):
    e = web.employee()
    uid = uuid.uuid4().hex
    r1 = gps(web, e, local(MONDAY, 8, 55), offset(0), event_uuid=uid)
    r2 = gps(web, e, local(MONDAY, 8, 55), offset(0), event_uuid=uid, now=local(MONDAY, 8, 56))
    assert r1.status_code == 201 and r2.status_code == 200 and r2.json()["duplicate"] and r2.json()["session_id"] == r1.json()["session_id"]
    r3 = gps(web, e, local(MONDAY, 9), offset(0))
    assert r3.status_code == 409 and r3.json()["code"] == "ALREADY_CHECKED_IN"
    # replay of a rejected attempt returns the same rejection
    bad = uuid.uuid4().hex
    assert gps(web, e, local(MONDAY, 9, 1), offset(900), event_uuid=bad, path="/attendance/check-in/").status_code in (409, 422)
    assert gps(web, e, local(MONDAY, 9, 1), offset(900), event_uuid=bad).json()["duplicate"]
    assert db.scalar(select(func.count()).select_from(LocationEvent).where(LocationEvent.client_event_id == uid)) == 1


def test_check_out_and_multiple_sessions(web):
    e = web.employee()
    gps(web, e, local(MONDAY, 9), offset(0))
    r = out(web, e, local(MONDAY, 12))
    assert r.status_code == 201 and r.json()["state"] == "CHECK_OUT_SUCCESS"
    assert out(web, e, local(MONDAY, 12, 5)).json()["code"] == "NOT_CHECKED_IN"
    gps(web, e, local(MONDAY, 13), offset(10))
    out(web, e, local(MONDAY, 18, 30))
    rec = web.today(e, local(MONDAY, 19))["record"]
    assert len(rec["sessions"]) == 2 and [s["duration_minutes"] for s in rec["sessions"]] == [180, 330]
    assert rec["worked_minutes"] == 510 and rec["overtime_minutes"] == 30 and rec["is_confirmed"]
    assert rec["sessions"][0]["check_in_event_id"] and rec["sessions"][0]["check_out_event_id"]


def test_checkout_requires_geofence_setting(web):
    web.settings(checkout_requires_geofence=True)
    e = web.employee()
    gps(web, e, local(MONDAY, 9), offset(0))
    assert out(web, e, local(MONDAY, 18), offset(900)).json()["state"] == "OUTSIDE_GEOFENCE"
    assert out(web, e, local(MONDAY, 18, 1), offset(10)).status_code == 201


def test_breaks(web):
    e = web.employee()
    gps(web, e, local(MONDAY, 9), offset(0))
    freeze(local(MONDAY, 13))
    assert web.post("/attendance/break/start/", {"type": "LUNCH"}, actor=e).status_code == 200
    assert web.post("/attendance/break/start/", {"type": "LUNCH"}, actor=e).status_code == 409
    freeze(local(MONDAY, 13, 40))
    r = web.post("/attendance/break/end/", {}, actor=e, expect=200).json()
    assert r["break_minutes"] == 40
    out(web, e, local(MONDAY, 18))
    assert web.today(e, local(MONDAY, 18, 5))["record"]["worked_minutes"] == 540 - 40


def test_offline_check_in_preserves_client_time(web, db):
    e = web.employee()
    r = gps(web, e, local(MONDAY, 8, 58), offset(0), now=local(MONDAY, 9, 40))  # queued offline for 42 min
    body = r.json()
    assert r.status_code == 201 and body["recorded_at"].startswith("2026-11-23T02:58") and body["received_at"].startswith("2026-11-23T03:40")
    assert web.today(e, local(MONDAY, 9, 45))["record"]["late_minutes"] == 0
    assert db.scalar(select(AttendanceAnomaly.type).where(AttendanceAnomaly.type == "DELAYED_SYNC"))


def test_passive_presence_does_not_create_attendance_in_web_mode(web):
    e = web.employee()
    web.arrive(e, local(MONDAY, 9))  # 3 stable inside readings
    t = web.today(e, local(MONDAY, 9, 2))
    assert t["record"] is None and t["location"]["presence"] == "INSIDE"


def test_manager_approval_policy(web):
    web.settings(confirmation_policy="MANAGER_APPROVAL")
    mgr = web.employee("Mia Manager", role="MANAGER", managed=[web.dept["id"]])
    e = web.employee()
    r = gps(web, e, local(MONDAY, 9), offset(0)).json()
    assert r["pending_approval"]
    rid = r["record_id"]
    assert web.today(e, local(MONDAY, 9, 5))["record"]["status"] == "PENDING_CONFIRMATION"
    assert web.post(f"/attendance/{rid}/confirm/", {}, actor=e).status_code == 409   # employee cannot self-approve
    assert web.post(f"/attendance/{rid}/approve/", {}, actor=e).status_code == 403   # not staff
    rows = web.get("/attendance/approvals/", actor=mgr).json()
    assert [x["employee_id"] for x in rows] == [e.employee_id]
    mrid = gps(web, mgr, local(MONDAY, 9, 1), offset(0)).json()["record_id"]
    assert web.post(f"/attendance/{mrid}/approve/", {}, actor=mgr).status_code == 403  # own attendance
    ok = web.post(f"/attendance/{rid}/approve/", {"approve": True}, actor=mgr, expect=200).json()
    assert ok["status"] == "PRESENT" and ok["sessions"][0]["approved_by_id"] and ok["is_confirmed"]


def test_employee_confirmation_policy_explicit_checkin_is_confirmation(web):
    web.settings(confirmation_policy="EMPLOYEE_CONFIRMATION")
    e = web.employee()
    r = gps(web, e, local(MONDAY, 9), offset(0)).json()
    assert not r["pending_approval"] and r["attendance_status"] == "PRESENT"


def test_dispute(web):
    e = web.employee()
    rid = gps(web, e, local(MONDAY, 9, 30), offset(0)).json()["record_id"]
    freeze(local(MONDAY, 10))
    c = web.post(f"/attendance/{rid}/dispute/", {"reason": "I was in at 9:00, GPS failed", "requested_check_in": local(MONDAY, 9).isoformat()},
                 actor=e, expect=201).json()
    assert c["type"] == "DISPUTE" and c["status"] == "PENDING"
    other = web.employee()
    assert web.post(f"/attendance/{rid}/dispute/", {"reason": "nope"}, actor=other).status_code == 404
    web.post(f"/attendance/corrections/{c['id']}/review/", {"approve": True}, expect=200)
    assert web.today(e, local(MONDAY, 10, 5))["record"]["late_minutes"] == 0


def test_repeated_failed_checkins_flagged(web, db):
    e = web.employee()
    for i in range(5):
        gps(web, e, local(MONDAY, 8, 50) + timedelta(seconds=40 * i), offset(400))
    with SessionLocal() as s:
        assert automation.detect_suspicious_location_events(s, local(MONDAY, 8, 55)) == 1
        assert automation.detect_suspicious_location_events(s, local(MONDAY, 8, 56)) == 0


def test_reminders_job(web, db):
    e = web.employee()
    def job(at):
        freeze(at)
        with SessionLocal() as s:
            return automation.send_attendance_reminders(s, at)

    assert job(local(MONDAY, 8, 52))["check_in"] == 1
    assert job(local(MONDAY, 8, 55))["check_in"] == 0
    gps(web, e, local(MONDAY, 9), offset(0))
    assert job(local(MONDAY, 18, 20))["check_out"] == 1
    assert job(local(MONDAY, 18, 25))["check_out"] == 0
    freeze(local(MONDAY, 18, 30))
    types = {n["type"] for n in web.get("/notifications/", actor=e).json()}
    assert {"CHECKIN_REMINDER", "CHECKOUT_REMINDER", "CHECK_IN"} <= types


def test_accountant_read_only(web):
    acc = web.employee("Ada Accountant", role="ACCOUNTANT", department=web.dept2)
    e = web.employee()
    gps(web, e, local(MONDAY, 9), offset(0))
    freeze(local(MONDAY, 10))
    assert web.get("/attendance/", actor=acc).json()["total"] == 1
    assert web.get("/reports/daily/", actor=acc, params={"date": "2026-11-23"}).status_code == 200
    assert web.get("/attendance/dashboard/", actor=acc).status_code == 200
    assert web.get("/locations/monitoring/", actor=acc).status_code == 403
    assert web.get("/attendance/approvals/", actor=acc).status_code == 403
    assert web.post("/offices/", {"name": "X", "latitude": 1, "longitude": 1}, actor=acc).status_code == 403
    rid = web.get("/attendance/", actor=acc).json()["items"][0]["id"]
    assert web.post(f"/attendance/{rid}/correction/", {"type": "OTHER", "reason": "edit"}, actor=acc).status_code == 403


def test_refresh_rotation_and_reuse_detection(web, client):
    e = web.employee()
    email = web.get(f"/employees/{e.employee_id}/").json()["email"]
    t1 = client.post("/api/v1/auth/login/", json={"email": email, "password": "Employee-pass1"}).json()
    t2 = client.post("/api/v1/auth/refresh/", json={"refresh_token": t1["refresh_token"]}).json()
    assert t2["refresh_token"] != t1["refresh_token"]
    # reuse of a rotated token -> 401 and the whole family (including t2) is revoked
    assert client.post("/api/v1/auth/refresh/", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh/", json={"refresh_token": t2["refresh_token"]}).status_code == 401
    # cookie-based refresh + logout
    client.cookies.clear()
    r = client.post("/api/v1/auth/login/", json={"email": email, "password": "Employee-pass1"})
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.post("/api/v1/auth/refresh/").status_code == 200  # uses cookie
    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.post("/api/v1/auth/refresh/").status_code == 401


def test_google_oauth(web, client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "google_client_id", None)
    assert client.post("/api/v1/auth/google/", json={"id_token": "x" * 40}).status_code == 503
    monkeypatch.setattr(get_settings(), "google_client_id", "client-123.apps.googleusercontent.com")
    ident = {"v": google_oauth.GoogleIdentity(sub="g-1", email="newboss@example.com", name="New Boss")}
    monkeypatch.setattr(google_oauth, "verify_id_token", lambda token, nonce=None: ident["v"])
    r = client.post("/api/v1/auth/google/", json={"id_token": "x" * 40})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "GOOGLE_ACCOUNT_NOT_FOUND"
    r = client.post("/api/v1/auth/google/", json={"id_token": "x" * 40, "company_name": "Google Co", "timezone": "Europe/Berlin", "company_type": "IT"})
    assert r.status_code == 200
    me = client.get("/api/v1/auth/me/", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "OWNER" and me["google_linked"] and not me["has_password"] and me["organization_name"] == "Google Co"
    # invited employee activates with Google (matched by verified email)
    inv = web.post("/employees/", {"full_name": "Gina Google", "email": "gina@example.com", "employee_code": "GG1"}, expect=201).json()
    ident["v"] = google_oauth.GoogleIdentity(sub="g-2", email="gina@example.com", name="Gina")
    r = client.post("/api/v1/auth/google/", json={"id_token": "x" * 40})
    assert r.status_code == 200 and web.get(f"/employees/{inv['id']}/").json()["invite_pending"] is False
    # a different Google account claiming the same email is refused
    ident["v"] = google_oauth.GoogleIdentity(sub="g-evil", email="gina@example.com", name="Gina")
    assert client.post("/api/v1/auth/google/", json={"id_token": "x" * 40}).status_code == 401


def test_google_verifier_rejects_bad_tokens(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "google_client_id", "client-123")

    class FakeKey:
        key = "irrelevant"

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            raise google_oauth.jwt.PyJWKClientError("no key")

    monkeypatch.setattr(google_oauth, "_jwks_client", lambda: FakeJwks())
    with pytest.raises(google_oauth.GoogleAuthError):
        google_oauth.verify_id_token("eyJhbGciOiJSUzI1NiJ9.e30.sig")


def test_plan_limits_and_billing(client):
    freeze(local(MONDAY, 6))
    w = World(client, "Tiny", auto_geofence=False)
    w.patch("/organizations/current/billing/", {"plan": "FREE"})
    b = w.get("/organizations/current/billing/").json()
    assert b["plan"]["code"] == "FREE" and b["payment_provider_connected"] is False
    r = w.post("/offices/", {"name": "Second", "latitude": 42.9, "longitude": 74.6})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "PLAN_LIMIT_REACHED"
    for i in range(10):
        w.post("/employees/", {"full_name": f"Emp {i}", "email": f"e{i}@tiny.example.com", "employee_code": f"T{i}"}, expect=201)
    assert w.post("/employees/", {"full_name": "Eleven", "email": "e11@tiny.example.com", "employee_code": "T11"}).status_code == 402
    assert client.get("/api/v1/plans/").json()[0]["code"] == "FREE"


def test_employee_and_office_delete(web, client):
    e = web.employee()
    assert web.c.delete(f"/api/v1/employees/{e.employee_id}/", headers=web.admin.headers).status_code == 204
    assert web.get("/auth/me/", actor=e).status_code == 401
    assert web.get(f"/employees/{e.employee_id}/").json()["employment_status"] == "TERMINATED"
    assert web.c.delete(f"/api/v1/offices/{web.office['id']}/", headers=web.admin.headers).status_code == 204
    o = web.get(f"/offices/{web.office['id']}/").json()
    assert o["is_active"] is False and o["geofence"]["enabled"] is False
    assert web.c.delete(f"/api/v1/departments/{web.dept2['id']}/", headers=web.admin.headers).status_code == 204


def test_organization_current(web):
    o = web.get("/organizations/current/").json()
    assert o["subscription_plan"] == "BUSINESS" and o["company_type"] == "OTHER"
    assert web.patch("/organizations/current/", {"company_type": "EDUCATION"}).json()["company_type"] == "EDUCATION"


def test_new_reports_and_kpis(web):
    a, b, c = web.employee("Ann"), web.employee("Bob"), web.employee("Cat")
    gps(web, a, local(MONDAY, 8, 50), offset(0))
    gps(web, b, local(MONDAY, 9, 40), offset(0))
    out(web, a, local(MONDAY, 19, 30))
    web.stream(c, local(MONDAY, 10), offset(3000))  # signal available, never came
    with SessionLocal() as s:
        automation.resolve_sessions(s, local(TUESDAY, 0, 10))
        automation.finalize_days(s, local(TUESDAY, 0, 30))
    freeze(local(TUESDAY, 9))
    trend = web.get("/reports/trends/", params={"start": "2026-11-23", "end": "2026-11-23"}).json()["series"][0]
    assert trend["present"] == 2 and trend["late"] == 1 and trend["absent"] == 1
    ab = web.get("/reports/absences/", params={"start": "2026-11-23", "end": "2026-11-23"}).json()
    assert ab["by_status"] == {"ABSENT": 1}
    ot = web.get("/reports/overtime/", params={"start": "2026-11-23", "end": "2026-11-23"}).json()
    assert ot["rows"][0]["employee_name"] == "Ann" and ot["rows"][0]["overtime_minutes"] > 0
    dept = web.get("/reports/departments/", params={"start": "2026-11-23", "end": "2026-11-23"}).json()["rows"]
    assert dept[0]["department"] == "Engineering" and dept[0]["attendance_rate"] == pytest.approx(66.7)
    csv = web.get("/reports/export/", params={"report": "absences", "start": "2026-11-23", "end": "2026-11-23"})
    assert csv.status_code == 200 and "ABSENT" in csv.text
    assert web.get("/reports/export/", params={"report": "nope"}).status_code == 422
    k = web.get("/attendance/dashboard/", params={"date": "2026-11-23"}).json()
    assert k["is_today"] is False and k["present"] == 2 and k["late"] == 1 and k["absent"] == 1 and k["overtime_minutes"] > 0
    assert k["avg_working_minutes"] > 0
    k2 = web.get("/attendance/dashboard/", params={"date": "2026-11-23", "department_id": web.dept2["id"]}).json()
    assert k2["total_employees"] == 0


def test_cross_tenant_check_in_uses_own_offices_only(client):
    freeze(local(MONDAY, 6))
    a, b = World(client, "TenantA", auto_geofence=False), World(client, "TenantB", auto_geofence=False)
    b.patch(f"/offices/{b.office['id']}/", {"latitude": OFFICE[0] + 0.1})  # B's office is 11 km away
    eb = b.employee()
    r = gps(b, eb, local(MONDAY, 9), offset(0))  # standing at A's office
    assert r.status_code == 422 and r.json()["state"] == "OUTSIDE_GEOFENCE" and r.json()["office_id"] == b.office["id"]
    assert a.get("/attendance/").json()["total"] == 0


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostGIS cross-check needs PostgreSQL")
def test_haversine_matches_postgis():
    with engine.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_extension WHERE extname='postgis'")).scalar():
            pytest.skip("PostGIS extension not installed")
        for (lat1, lon1), (lat2, lon2) in [(OFFICE, offset(95)), (OFFICE, offset(1500, 700)), ((42.8746, 74.5698), (43.2389, 76.8897))]:
            pg = c.execute(text("SELECT ST_DistanceSphere(ST_MakePoint(:a, :b), ST_MakePoint(:c, :d))"),
                           {"a": lon1, "b": lat1, "c": lon2, "d": lat2}).scalar()
            assert geo.haversine_m(lat1, lon1, lat2, lon2) == pytest.approx(pg, rel=1e-3)
