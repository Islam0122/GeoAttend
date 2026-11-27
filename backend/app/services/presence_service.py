"""PresenceDetectionService — resolves what managers and employees see, from server-validated data only.

Three independent dimensions (never mixed):

zone_status (physical presence, from the latest server-validated reading)
  NO_OFFICE         employee has no assigned active office geofence
  LOCATION_DENIED   the employee's browser reported location permission denied (after the last valid reading)
  INSIDE / OUTSIDE  last validated reading (accuracy within the office maximum, unambiguous zone) is fresh
  LOCATION_DETECTED fresh readings exist but none could be validated (inaccurate GPS / geofence boundary)
  STALE             readings exist but the last one is older than `presence_stale_seconds` (tab closed, offline…)
  UNKNOWN           no location check was ever received

session_status (work session):  ACTIVE · TEMPORARY_EXIT · PENDING_CHECKOUT · COMPLETED · NOT_STARTED
attendance_status (the day):    record status (PRESENT, LATE, UNSCHEDULED, ...) · NOT_CHECKED_IN · NO_SHIFT

Stale or missing data never changes the session: it only changes zone_status.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import local_date
from app.models import AttendanceRecord, AttendanceSession, DeviceRegistration, Employee, GeofenceState, Office, OrganizationSettings
from app.models.enums import PermissionStatus, SessionStatus, Zone
from app.services import attendance_service as att
from app.services.schedule_service import employee_timezone, shift_for_date, shift_for_instant

DENIED = {PermissionStatus.DENIED, PermissionStatus.RESTRICTED}

ZONE_STATUSES = ["INSIDE", "OUTSIDE", "LOCATION_DETECTED", "STALE", "UNKNOWN", "LOCATION_DENIED", "NO_OFFICE"]
SESSION_STATUSES = ["ACTIVE", "TEMPORARY_EXIT", "PENDING_CHECKOUT", "COMPLETED", "NOT_STARTED"]


@dataclass
class PresenceView:
    zone_status: str
    reason: str
    office_id: int | None = None
    assigned_office_ids: list[int] = field(default_factory=list)
    distance_m: float | None = None
    accuracy_m: float | None = None
    last_update: datetime | None = None          # time of the reading behind zone_status
    last_validated_at: datetime | None = None
    validated_zone: str | None = None
    last_activity: datetime | None = None        # latest reading or device heartbeat
    permission: str | None = None
    consent_granted: bool = False
    session_status: str = "NOT_STARTED"
    live_session_status: str | None = None
    session_id: int | None = None
    record_id: int | None = None
    attendance_status: str = "NOT_CHECKED_IN"
    check_in_time: datetime | None = None
    check_out_time: datetime | None = None
    working_minutes: int = 0
    late_minutes: int = 0
    temporary_exit_started_at: datetime | None = None
    temporary_exit_minutes: int = 0
    is_unscheduled: bool = False

    @property
    def status(self) -> str:  # backward compatible "presence"
        return self.zone_status

    def as_dict(self) -> dict:
        return asdict(self)


def _today_record(db: Session, emp: Employee, now: datetime, settings: OrganizationSettings) -> AttendanceRecord | None:
    live = att.live_session(db, emp.id)
    if live is not None:
        return live.record
    shift = shift_for_instant(db, emp, now, settings) or shift_for_date(db, emp, local_date(now, employee_timezone(db, emp)), settings)
    day = shift.work_date if shift else local_date(now, employee_timezone(db, emp))
    return db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.work_date == day))


def resolve(db: Session, emp: Employee, now: datetime, *, settings: OrganizationSettings | None = None,
            recompute_live: bool = False) -> PresenceView:
    from app.services.location_service import candidate_offices, current_consent  # local import: avoid cycle

    settings = settings or att.org_settings(db, emp.organization_id)
    offices: list[Office] = candidate_offices(db, emp)
    office_ids = [o.id for o in offices]
    consent = current_consent(db, emp.id)
    dev = db.scalar(select(DeviceRegistration).where(DeviceRegistration.employee_id == emp.id, DeviceRegistration.is_active.is_(True))
                    .order_by(DeviceRegistration.last_seen_at.desc().nulls_last()).limit(1))
    states = list(db.scalars(select(GeofenceState).where(GeofenceState.employee_id == emp.id, GeofenceState.office_id.in_(office_ids or [-1]))).all())

    validated = [s for s in states if s.last_validated_at is not None]
    best = None
    if validated:
        newest = max(s.last_validated_at for s in validated)
        same = [s for s in validated if s.last_validated_at == newest]
        best = (next((s for s in same if s.last_validated_zone == Zone.INSIDE and s.office_id == emp.primary_office_id), None)
                or next((s for s in same if s.last_validated_zone == Zone.INSIDE), None)
                or min(same, key=lambda s: s.last_validated_distance_m if s.last_validated_distance_m is not None else 1e12))
    readings = [s for s in states if s.last_recorded_at is not None]
    latest = max(readings, key=lambda s: s.last_recorded_at) if readings else None
    fresh_after = now - timedelta(seconds=settings.presence_stale_seconds)
    perm_at = (dev.permission_updated_at or dev.last_seen_at) if dev else None

    v = PresenceView(zone_status="UNKNOWN", reason="No location check has been received yet.", assigned_office_ids=office_ids,
                     permission=dev.location_permission.value if dev else None, consent_granted=bool(consent and consent.granted),
                     last_activity=max([t for t in (latest.last_recorded_at if latest else None, dev.last_seen_at if dev else None) if t], default=None))
    if best is not None:
        v.last_validated_at, v.validated_zone = best.last_validated_at, best.last_validated_zone.value

    if not offices:
        v.zone_status, v.reason = "NO_OFFICE", "No active office geofence is assigned to this employee."
    elif dev is not None and dev.location_permission in DENIED and (best is None or (perm_at and perm_at >= best.last_validated_at)):
        v.zone_status, v.reason = "LOCATION_DENIED", "Location permission is blocked in the employee's browser."
    elif best is not None and best.last_validated_at >= fresh_after:
        v.zone_status = best.last_validated_zone.value
        v.office_id, v.distance_m, v.accuracy_m, v.last_update = best.office_id, _r(best.last_validated_distance_m), best.last_validated_accuracy_m, best.last_validated_at
        v.reason = f"Server-validated reading {'inside' if v.zone_status == 'INSIDE' else 'outside'} the geofence."
    elif latest is not None and latest.last_recorded_at >= fresh_after:
        v.zone_status = "LOCATION_DETECTED"
        v.office_id, v.distance_m, v.accuracy_m, v.last_update = latest.office_id, _r(latest.last_distance_m), latest.last_accuracy_m, latest.last_recorded_at
        v.reason = "Location received but not precise enough to confirm inside/outside (GPS accuracy or geofence boundary)."
    elif best is not None or latest is not None:
        src = best or latest
        v.zone_status = "STALE"
        v.office_id = src.office_id
        v.distance_m = _r(best.last_validated_distance_m if best else latest.last_distance_m)
        v.accuracy_m = best.last_validated_accuracy_m if best else latest.last_accuracy_m
        v.last_update = best.last_validated_at if best else latest.last_recorded_at
        v.reason = f"Last location check is older than {settings.presence_stale_seconds // 60 or 1} min (attendance screen closed or offline)."
    elif not v.consent_granted:
        v.reason = "Employee has not given location consent yet."

    # ---- session and attendance (independent of the zone) ----
    record = _today_record(db, emp, now, settings)
    live = att.live_session(db, emp.id)
    if record is not None:
        if recompute_live and not record.is_finalized:
            att.recompute(db, record, now)
        v.record_id, v.attendance_status = record.id, record.status.value
        v.check_in_time, v.check_out_time = record.actual_check_in, record.actual_check_out
        v.working_minutes, v.late_minutes, v.temporary_exit_minutes = record.worked_minutes, record.late_minutes, record.temporary_exit_minutes
        v.is_unscheduled = record.is_unscheduled
    else:
        has_shift = shift_for_instant(db, emp, now, settings) or shift_for_date(db, emp, local_date(now, employee_timezone(db, emp)), settings)
        v.attendance_status = "NOT_CHECKED_IN" if has_shift else "NO_SHIFT"
    if live is not None:
        v.session_id, v.live_session_status = live.id, live.status.value
        if live.status == SessionStatus.AWAY:
            v.session_status = "TEMPORARY_EXIT"
            brk = att._open_break(live)  # noqa: SLF001
            v.temporary_exit_started_at = brk.started_at if brk else None
        else:
            v.session_status = "ACTIVE"
    elif record is not None and record.sessions:
        sessions: list[AttendanceSession] = list(record.sessions)
        v.session_id = sessions[-1].id
        v.session_status = "PENDING_CHECKOUT" if any(s.status == SessionStatus.PENDING_CHECKOUT for s in sessions) else "COMPLETED"
    return v


def _r(x: float | None) -> float | None:
    return round(x, 1) if x is not None else None
