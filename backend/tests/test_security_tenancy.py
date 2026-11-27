"""Multi-tenancy isolation, RBAC, auth, rate limiting, concurrency, deferred processing, push, retention."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core import rate_limit
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import AttendanceSession, LocationEvent, Notification
from app.models.enums import DeliveryStatus
from app.services import automation, location_service, notifications
from tests.conftest import MONDAY, World, freeze, local, offset


@pytest.fixture
def two(client):
    freeze(local(MONDAY, 6))
    return World(client, "Alpha"), World(client, "Bravo")


def test_company_a_cannot_access_company_b(two):
    a, b = two
    ea, eb = a.employee(), b.employee()
    a.arrive(ea, local(MONDAY, 9))
    freeze(local(MONDAY, 10))
    rec_a = a.get("/attendance/", actor=ea).json()["items"][0]["id"]
    # B's admin cannot read A's office, geofence, employee or attendance
    assert b.get(f"/offices/{a.office['id']}/").status_code == 404
    assert b.patch(f"/offices/{a.office['id']}/geofence/", {"radius_m": 500}).status_code == 404
    assert b.get(f"/employees/{ea.employee_id}/").status_code == 404
    assert b.get(f"/attendance/{rec_a}/").status_code == 404
    assert b.post(f"/attendance/{rec_a}/correction/", {"type": "OTHER", "reason": "hack"}).status_code == 404
    assert all(o["id"] != a.office["id"] for o in b.get("/offices/").json())
    assert b.get("/attendance/").json()["total"] == 0
    assert {r["employee_id"] for r in b.get("/reports/daily/", params={"date": "2026-11-23"}).json()["rows"]} == {eb.employee_id}
    assert b.get("/locations/monitoring/").json()[0]["employee_id"] == eb.employee_id
    # cannot assign another tenant's employee to own office or schedule
    assert b.patch(f"/offices/{b.office['id']}/", {"employee_ids": [ea.employee_id]}).status_code == 422
    assert b.post("/schedules/assignments/", {"schedule_id": b.schedule["id"], "employee_id": ea.employee_id, "effective_from": "2026-01-01"}).status_code == 404
    # B's employee is never evaluated against A's office
    r = b.arrive(eb, local(MONDAY, 9))
    assert r.json()["office_id"] == b.office["id"]


def test_employee_cannot_access_other_employee(world):
    e1, e2 = world.employee("Ann"), world.employee("Bob")
    world.arrive(e1, local(MONDAY, 9))
    freeze(local(MONDAY, 10))
    rid = world.get("/attendance/", actor=e1).json()["items"][0]["id"]
    assert world.get(f"/attendance/{rid}/", actor=e2).status_code == 404
    assert world.post(f"/attendance/{rid}/confirm/", {}, actor=e2).status_code == 404
    assert world.get("/attendance/", actor=e2).json()["total"] == 0
    assert world.get("/employees/", actor=e2).status_code == 403
    assert world.get("/locations/monitoring/", actor=e2).status_code == 403
    assert world.get("/anomalies/", actor=e2).status_code == 403
    assert world.post("/offices/", {"name": "X", "latitude": 1, "longitude": 1}, actor=e2).status_code == 403
    assert world.patch("/organizations/current/settings/", {"required_consecutive": 1}, actor=e2).status_code == 403
    assert world.get("/reports/daily/", actor=e2, params={"date": "2026-11-23"}).status_code == 403
    mine = world.get("/reports/me/", actor=e2, params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert [r["employee_id"] for r in mine["rows"]] == [e2.employee_id]


def test_manager_limited_to_departments(world):
    mgr = world.employee("Manny", role="MANAGER", managed=[world.dept["id"]])
    eng = world.employee("Eng", department=world.dept)
    sales = world.employee("Sal", department=world.dept2)
    world.arrive(eng, local(MONDAY, 9))
    world.arrive(sales, local(MONDAY, 9))
    freeze(local(MONDAY, 10))
    ids = {e["id"] for e in world.get("/employees/", actor=mgr).json()["items"]}
    assert eng.employee_id in ids and sales.employee_id not in ids
    assert world.get(f"/employees/{sales.employee_id}/", actor=mgr).status_code == 404
    recs = world.get("/attendance/", actor=mgr).json()["items"]
    assert {r["employee_id"] for r in recs} == {eng.employee_id}
    sales_rec = world.get("/attendance/", actor=sales).json()["items"][0]["id"]
    assert world.get(f"/attendance/{sales_rec}/", actor=mgr).status_code == 404
    assert {r["employee_id"] for r in world.get("/locations/monitoring/", actor=mgr).json()} == {mgr.employee_id, eng.employee_id}
    # managers cannot change organization configuration
    assert world.post("/offices/", {"name": "X", "latitude": 1, "longitude": 1}, actor=mgr).status_code == 403
    assert world.post("/employees/", {"full_name": "New Guy", "email": "n@x.example.com", "employee_code": "N1"}, actor=mgr).status_code == 403


def test_authentication(world, client):
    assert client.get("/api/v1/attendance/").status_code == 401
    assert client.get("/api/v1/attendance/", headers={"Authorization": "Bearer garbage"}).status_code == 401
    e = world.employee()
    # refresh token cannot be used as an access token
    r = client.post("/api/v1/auth/login/", json={"email": world.get("/employees/").json()["items"][0]["email"], "password": "Employee-pass1"})
    tokens = r.json()
    assert client.get("/api/v1/auth/me/", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401
    assert client.post("/api/v1/auth/refresh/", json={"refresh_token": tokens["refresh_token"]}).status_code == 200
    # password change revokes old tokens
    world.post("/auth/change-password/", {"current_password": "Employee-pass1", "new_password": "Brand-new-pass2"}, actor=e, expect=204)
    assert world.get("/auth/me/", actor=e).status_code == 401
    assert client.post("/api/v1/auth/refresh/", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/login/", json={"email": "nobody@x.example.com", "password": "whatever-123"}).status_code == 401


def test_token_expiry(client, monkeypatch):
    freeze(local(MONDAY, 6))
    w = World(client, "Expire")
    monkeypatch.setattr(get_settings(), "access_token_minutes", 30)
    tok = client.post("/api/v1/auth/login/", json={"email": client.get("/api/v1/auth/me/", headers=w.admin.headers).json()["email"], "password": "Sup3r-secret!"}).json()
    freeze(local(MONDAY, 6, 29))
    assert client.get("/api/v1/auth/me/", headers={"Authorization": f"Bearer {tok['access_token']}"}).status_code == 200
    freeze(local(MONDAY, 6, 31))
    assert client.get("/api/v1/auth/me/", headers={"Authorization": f"Bearer {tok['access_token']}"}).status_code == 401


def test_invite_token_single_use(world, client):
    r = world.post("/employees/", {"full_name": "Ivy Invite", "email": "ivy@x.example.com", "employee_code": "IVY"}, expect=201).json()
    token = r["invite_url"].split("token=")[1]
    assert client.post("/api/v1/auth/accept-invite/", json={"token": token, "password": "Ivy-password1"}).status_code == 200
    assert client.post("/api/v1/auth/accept-invite/", json={"token": token, "password": "Ivy-password2"}).status_code == 400


def test_validation_errors(world):
    assert world.post("/offices/", {"name": "Bad", "latitude": 91, "longitude": 0}).status_code == 422
    assert world.patch(f"/offices/{world.office['id']}/geofence/", {"radius_m": 5}).status_code == 422
    assert world.patch(f"/offices/{world.office['id']}/geofence/", {"max_accuracy_m": 0}).status_code == 422
    assert world.post("/offices/", {"name": "TZ", "latitude": 1, "longitude": 1, "timezone": "Mars/Base"}).status_code == 422
    assert world.post("/schedules/", {"name": "Dup", "days": [{"weekday": 0, "start_time": "09:00", "end_time": "17:00"}] * 2}).status_code == 422
    assert world.patch("/organizations/current/settings/", {"required_consecutive": 0}).status_code == 422
    e = world.employee()
    assert world.post("/locations/batch/", {"events": []}, actor=e).status_code == 422
    assert world.post("/consent/", {"granted": True, "consent_version": "0.1"}, actor=e).status_code == 422


def test_geofence_settings_are_applied(world, db):
    world.patch(f"/offices/{world.office['id']}/geofence/", {"required_consecutive": 1, "stability_window_seconds": 0, "radius_m": 300})
    e = world.employee()
    r = world.send(e, local(MONDAY, 9), offset(250))
    assert r.json()["transition"] == "ENTER"
    world.patch(f"/offices/{world.office['id']}/geofence/", {"enabled": False})
    e2 = world.employee()
    assert world.send(e2, local(MONDAY, 9), offset(0)).json()["result"] == "NO_OFFICE"


def test_rate_limiting(world, monkeypatch):
    e = world.employee()
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    monkeypatch.setattr(s, "rate_limit_locations", "5/60")
    rate_limit.backend().reset()
    codes = [world.send(e, local(MONDAY, 9) + timedelta(seconds=i * 30), offset(0)).status_code for i in range(7)]
    assert codes[:5] == [201] * 5 and codes[5:] == [429, 429]
    rate_limit.backend().reset()


def test_auth_rate_limit(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    monkeypatch.setattr(s, "rate_limit_auth", "3/60")
    rate_limit.backend().reset()
    codes = [client.post("/api/v1/auth/login/", json={"email": "x@y.example.com", "password": "nope-nope"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]
    # a colleague behind the same office IP is not locked out
    assert client.post("/api/v1/auth/login/", json={"email": "other@y.example.com", "password": "nope-nope"}).status_code == 401
    monkeypatch.setattr(s, "rate_limit_auth_ip", "6/60")  # 7th request from this IP
    assert client.post("/api/v1/auth/login/", json={"email": "third@y.example.com", "password": "nope-nope"}).status_code == 429
    rate_limit.backend().reset()


def test_concurrent_duplicate_events(world):
    """Many parallel requests with the same event id -> exactly one stored event and one session."""
    e = world.employee()
    world.send(e, local(MONDAY, 9), offset(0))
    world.send(e, local(MONDAY, 9, 0, 30), offset(0))
    freeze(local(MONDAY, 9, 2))
    fix = world.fix(e, local(MONDAY, 9, 1), offset(0))
    codes, errors = [], []

    def hit():
        try:
            codes.append(world.c.post("/api/v1/locations/events/", json=fix, headers=e.headers).status_code)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=hit) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and sorted(set(codes)) <= [200, 201] and codes.count(201) == 1
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(LocationEvent).where(LocationEvent.client_event_id == fix["client_event_id"])) == 1
        assert s.scalar(select(func.count()).select_from(AttendanceSession)) == 1


def test_concurrent_distinct_events_single_session(world):
    """Parallel arrival readings from a fast sync must not open two live sessions."""
    e = world.employee()
    freeze(local(MONDAY, 9, 5))
    fixes = [world.fix(e, local(MONDAY, 9) + timedelta(seconds=20 * i), offset(0)) for i in range(10)]
    results = []

    def hit(f):
        results.append(world.c.post("/api/v1/locations/events/", json=f, headers=e.headers).status_code)

    threads = [threading.Thread(target=hit, args=(f,)) for f in fixes]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(c in (200, 201) for c in results)
    with SessionLocal() as s:
        # Arbitrary interleaving may mark some fixes OUT_OF_ORDER, but there can never be two live sessions.
        live = s.scalar(select(func.count()).select_from(AttendanceSession).where(AttendanceSession.status.in_(["OPEN", "AWAY"])))
        assert live <= 1
        assert s.scalar(select(func.count()).select_from(LocationEvent)) == 10


def test_db_enforces_single_live_session(world):
    """The partial unique index is the last line of defence against races."""
    from sqlalchemy.exc import IntegrityError

    from app.models import AttendanceRecord
    from app.models.enums import SessionConfirmation, SessionStatus

    e = world.employee()
    world.arrive(e, local(MONDAY, 9))
    with SessionLocal() as s:
        rec = s.scalar(select(AttendanceRecord))
        s.add(AttendanceSession(organization_id=rec.organization_id, record_id=rec.id, employee_id=e.employee_id, status=SessionStatus.OPEN,
                                confirmation=SessionConfirmation.AUTO_CONFIRMED, check_in_at=local(MONDAY, 10)))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        # a CLOSED session for the same employee is fine
        s.add(AttendanceSession(organization_id=rec.organization_id, record_id=rec.id, employee_id=e.employee_id, status=SessionStatus.CLOSED,
                                confirmation=SessionConfirmation.AUTO_CONFIRMED, check_in_at=local(MONDAY, 7), check_out_at=local(MONDAY, 8)))
        s.commit()


def test_deferred_processing_on_failure(world, monkeypatch):
    e = world.employee()
    world.send(e, local(MONDAY, 9), offset(0))
    world.send(e, local(MONDAY, 9, 0, 30), offset(0))
    original = location_service.evaluate_event
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        raise RuntimeError("downstream outage")

    monkeypatch.setattr(location_service, "evaluate_event", flaky)
    r = world.send(e, local(MONDAY, 9, 1), offset(0))
    assert r.status_code == 201 and r.json()["result"] == "PENDING"
    monkeypatch.setattr(location_service, "evaluate_event", original)
    freeze(local(MONDAY, 9, 5))
    with SessionLocal() as s:
        stats = automation.process_delayed_events(s, local(MONDAY, 9, 5))
    assert stats["processed"] == 1
    rec = world.today(e, local(MONDAY, 9, 10))["record"]
    assert rec["actual_check_in"].startswith("2026-11-23T03:00")


def test_notification_email_outbox(world, monkeypatch):
    e = world.employee()
    with SessionLocal() as s:
        from app.services.notifications import notify_employee
        from app.models import Employee
        notify_employee(s, s.get(Employee, e.employee_id), type="CHECKIN_REMINDER", title="Shift soon", body="Check in")
        s.commit()
        assert notifications.deliver_pending(s)["skipped"] >= 1  # SMTP not configured -> in-app only
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    sent = []
    monkeypatch.setattr(notifications, "send_email", lambda to, subject, body: sent.append((to, subject)) or True)
    with SessionLocal() as s:
        from app.services.notifications import notify_employee
        from app.models import Employee
        notify_employee(s, s.get(Employee, e.employee_id), type="CHECKIN_REMINDER", title="Shift soon", body="Check in")
        notify_employee(s, s.get(Employee, e.employee_id), type="CHECK_IN", title="Checked in", body="ok")  # in-app only type
        s.commit()
        stats = notifications.deliver_pending(s)
        assert stats["sent"] == 1 and stats["skipped"] == 1
        assert s.scalar(select(Notification.push_status).where(Notification.type == "CHECKIN_REMINDER").order_by(Notification.id.desc())) == DeliveryStatus.SENT
    assert sent[0][1] == "Shift soon"


def test_permission_revocation_is_informational(world):
    e = world.employee()
    world.post("/devices/heartbeat/", {"device_id": e.device_id, "location_permission": "DENIED"}, actor=e, expect=200)
    an = world.get("/anomalies/").json()
    assert an[0]["type"] == "PERMISSION_REVOKED" and an[0]["severity"] == "INFO"
    world.post(f"/anomalies/{an[0]['id']}/review/", {"status": "DISMISSED", "comment": "Phone replaced"}, expect=200)
    assert world.get("/anomalies/").json() == []


def test_hr_anomaly_notification(world, db):
    e = world.employee()
    world.send(e, local(MONDAY, 9), offset(0), is_mocked=True)
    with SessionLocal() as s:
        assert automation.notify_hr_anomalies(s, local(MONDAY, 9, 10)) == 1
        assert automation.notify_hr_anomalies(s, local(MONDAY, 9, 20)) == 0
    assert any(n["type"] == "ANOMALIES" for n in world.get("/notifications/").json())


def test_coordinate_retention_purge(world):
    e = world.employee()
    world.send(e, local(MONDAY, 9), offset(0))
    with SessionLocal() as s:
        assert automation.purge_old_coordinates(s, local(MONDAY, 9) + timedelta(days=91)) == 1
        ev = s.scalar(select(LocationEvent))
        assert ev.latitude is None and ev.coordinates_purged and ev.distance_m is not None


def test_audit_log_for_configuration_changes(world):
    world.patch(f"/offices/{world.office['id']}/geofence/", {"radius_m": 150})
    world.settings(confirmation_policy="EMPLOYEE_CONFIRMATION")
    actions = {l["action"] for l in world.get("/audit-logs/").json()["items"]}
    assert {"geofence.updated", "settings.updated", "office.created", "organization.registered"} <= actions
    entry = next(l for l in world.get("/audit-logs/").json()["items"] if l["action"] == "geofence.updated")
    assert entry["changes"]["radius_m"] == {"old": 100.0, "new": 150.0}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert engine is not None and uuid  # silence linters
