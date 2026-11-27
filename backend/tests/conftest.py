"""Test harness. Uses a throwaway SQLite file by default; set TEST_DATABASE_URL to run against PostgreSQL."""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

_tmp = tempfile.mkdtemp(prefix="geoattend-test-")
os.environ["GEOATTEND_DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["GEOATTEND_RATE_LIMIT_ENABLED"] = "false"
os.environ["GEOATTEND_LOG_JSON"] = "false"
os.environ["GEOATTEND_LOG_LEVEL"] = "WARNING"
os.environ["GEOATTEND_BCRYPT_ROUNDS"] = "4"
os.environ["GEOATTEND_ACCESS_TOKEN_MINUTES"] = "525600"
os.environ.pop("GEOATTEND_REDIS_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.core import timeutils  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

UTC = timezone.utc
TZ = "Asia/Bishkek"  # UTC+6, no DST
OFFICE = (42.874600, 74.569800)
MONDAY = date(2026, 11, 23)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean():
    yield
    timeutils.set_now(None)
    with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            names = ", ".join(t.name for t in Base.metadata.sorted_tables)
            c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for t in reversed(Base.metadata.sorted_tables):
                c.execute(t.delete())


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def local(day: date, hh: int, mm: int = 0, ss: int = 0, tz: str = TZ) -> datetime:
    return timeutils.local_to_utc(day, time(hh, mm, ss), tz)


def offset(meters_north: float, meters_east: float = 0.0, base: tuple[float, float] = OFFICE) -> tuple[float, float]:
    import math

    lat = base[0] + meters_north / 111_320.0
    lng = base[1] + meters_east / (111_320.0 * math.cos(math.radians(base[0])))
    return lat, lng


def freeze(t: datetime) -> None:
    timeutils.set_now(t)


@dataclass
class Actor:
    headers: dict
    user_id: int | None = None
    employee_id: int | None = None
    device_id: str = ""


class World:
    """Builds a realistic tenant through the public API (register -> office -> schedule -> invite -> consent -> device)."""

    def __init__(self, client: TestClient, name: str = "Acme", tz: str = TZ, auto_geofence: bool = True):
        self.c = client
        self.tz = tz
        email = f"owner-{uuid.uuid4().hex[:8]}@{name.lower()}.example.com"
        r = client.post("/api/v1/auth/register-company/", json={"company_name": name, "timezone": tz, "full_name": "Olivia Owner", "email": email, "password": "Sup3r-secret!"})
        assert r.status_code == 201, r.text
        self.admin = Actor(headers={"Authorization": f"Bearer {r.json()['access_token']}"})
        # Hybrid suites exercise passive geofence attendance; web check-in suites pass auto_geofence=False.
        self.settings(auto_geofence_attendance=auto_geofence)
        self.patch("/organizations/current/billing/", {"plan": "BUSINESS"})
        self.dept = self.post("/departments/", {"name": "Engineering"}).json()
        self.dept2 = self.post("/departments/", {"name": "Sales"}).json()
        self.office = self.post("/offices/", {"name": "HQ", "latitude": OFFICE[0], "longitude": OFFICE[1], "timezone": tz}).json()
        self.schedule = self.post("/schedules/", {
            "name": "Standard", "grace_period_minutes": 10,
            "days": [{"weekday": d, "start_time": "09:00", "end_time": "18:00", "break_start": "13:00", "break_end": "14:00"} for d in range(5)],
        }).json()

    # -- http helpers
    def post(self, path, body=None, actor: Actor | None = None, expect: int | None = None, **kw):
        r = self.c.post(f"/api/v1{path}", json=body, headers=(actor or self.admin).headers, **kw)
        if expect is not None:
            assert r.status_code == expect, r.text
        return r

    def patch(self, path, body, actor: Actor | None = None):
        return self.c.patch(f"/api/v1{path}", json=body, headers=(actor or self.admin).headers)

    def get(self, path, actor: Actor | None = None, **kw):
        return self.c.get(f"/api/v1{path}", headers=(actor or self.admin).headers, **kw)

    def settings(self, **values):
        r = self.patch("/organizations/current/settings/", values)
        assert r.status_code == 200, r.text

    def employee(self, name="Eve Employee", role="EMPLOYEE", department=None, schedule=True, consent=True, device=True, offices=None, managed=None) -> Actor:
        code = uuid.uuid4().hex[:6]
        body = {"full_name": name, "email": f"{code}@staff.example.com", "employee_code": code, "role": role,
                "department_id": (department or self.dept)["id"], "office_ids": offices if offices is not None else [self.office["id"]],
                "managed_department_ids": managed or []}
        r = self.post("/employees/", body, expect=201)
        emp = r.json()
        token = emp["invite_url"].split("token=")[1]
        r = self.c.post("/api/v1/auth/accept-invite/", json={"token": token, "password": "Employee-pass1"})
        assert r.status_code == 200, r.text
        a = Actor(headers={"Authorization": f"Bearer {r.json()['access_token']}"}, user_id=emp["user_id"], employee_id=emp["id"], device_id=f"dev-{code}")
        if schedule:
            self.post("/schedules/assignments/", {"schedule_id": self.schedule["id"], "employee_id": emp["id"], "effective_from": "2026-01-01"}, expect=201)
        if consent:
            self.post("/consent/", {"granted": True, "consent_version": "1.0"}, actor=a, expect=201)
        if device:
            self.post("/devices/register/", {"device_id": a.device_id, "platform": "ANDROID", "location_permission": "GRANTED_ALWAYS", "background_enabled": True}, actor=a, expect=200)
        return a

    # -- GPS helpers
    def fix(self, a: Actor, at: datetime, lat_lng: tuple[float, float], accuracy: float = 10.0, **extra) -> dict:
        return {"client_event_id": extra.pop("client_event_id", uuid.uuid4().hex), "device_id": extra.pop("device_id", a.device_id),
                "latitude": lat_lng[0], "longitude": lat_lng[1], "accuracy": accuracy, "recorded_at": at.isoformat(),
                "platform": "ANDROID", "permission_status": "GRANTED_ALWAYS", **extra}

    def send(self, a: Actor, at: datetime, lat_lng, accuracy=10.0, now: datetime | None = None, **extra):
        freeze(now or at + timedelta(seconds=2))
        return self.c.post("/api/v1/locations/events/", json=self.fix(a, at, lat_lng, accuracy, **extra), headers=a.headers)

    def stream(self, a: Actor, start: datetime, lat_lng, n: int = 3, step_s: int = 30, accuracy: float = 10.0):
        """n readings `step_s` apart; returns the last response."""
        r = None
        for i in range(n):
            r = self.send(a, start + timedelta(seconds=i * step_s), lat_lng, accuracy)
            assert r.status_code in (200, 201), r.text
        return r

    def arrive(self, a: Actor, at: datetime):
        return self.stream(a, at, offset(0))

    def leave(self, a: Actor, at: datetime):
        return self.stream(a, at, offset(800))

    def today(self, a: Actor, now: datetime) -> dict:
        freeze(now)
        r = self.get("/attendance/today/", actor=a)
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def world(client) -> World:
    freeze(datetime(2026, 11, 20, 6, 0, tzinfo=UTC))
    return World(client)
