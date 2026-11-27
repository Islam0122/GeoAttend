"""Scheduled automation (invoked by Celery beat). Every job is idempotent and timezone-aware:
decisions are made per employee shift (employee/office timezone), never on server-local time."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.timeutils import day_bounds_utc, local_date
from app.models import (
    AttendanceAnomaly,
    AttendanceRecord,
    AttendanceSession,
    Employee,
    LocationEvent,
    Organization,
    ReportSnapshot,
)
from app.models.enums import (
    AnomalySeverity,
    AnomalyType,
    ReportType,
    SessionConfirmation,
    SessionStatus,
)
from app.services import attendance_service as att
from app.services import location_service, reports
from app.services.anomalies import raise_anomaly
from app.services.notifications import notify_employee, notify_hr
from app.services.schedule_service import shift_for_date

log = logging.getLogger("geoattend.automation")


def _orgs(db: Session) -> list[Organization]:
    return list(db.scalars(select(Organization).where(Organization.is_active.is_(True))).all())


def _employees(db: Session, org_id: int) -> list[Employee]:
    return list(db.scalars(select(Employee).where(Employee.organization_id == org_id, Employee.is_active.is_(True))).unique().all())


def detect_missing_checkins(db: Session, now: datetime) -> int:
    """Shift started (+grace +threshold), no session, not on leave -> notify employee + HR once."""
    count = 0
    for org in _orgs(db):
        settings = att.org_settings(db, org.id)
        for emp in _employees(db, org.id):
            for offset in (0, -1):
                tz_today = local_date(now, org.timezone)
                shift = shift_for_date(db, emp, tz_today + timedelta(days=offset), settings)
                if shift is None:
                    continue
                due = shift.start + timedelta(minutes=shift.grace_period_minutes + settings.missing_checkin_after_minutes)
                if not (due <= now <= shift.end):
                    continue
                if att.has_leave(db, emp.id, shift.start, shift.end):
                    continue
                rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.work_date == shift.work_date))
                if rec is not None and (rec.sessions or rec.missing_checkin_notified_at):
                    continue
                rec = att.get_or_create_record(db, emp, shift)
                rec.missing_checkin_notified_at = now
                att.recompute(db, rec, now)
                notify_employee(db, emp, type="MISSING_CHECK_IN", title="Arrival not detected",
                                body="We have not detected your arrival yet. Open the app to check location access, or request a correction.",
                                data={"record_id": rec.id})
                raise_anomaly(db, org_id=org.id, employee_id=emp.id, type=AnomalyType.MISSING_CHECK_IN, severity=AnomalySeverity.INFO,
                              record_id=rec.id, work_date=shift.work_date, details={"scheduled_start": shift.start.isoformat()})
                count += 1
    db.commit()
    return count


def resolve_sessions(db: Session, now: datetime) -> dict[str, int]:
    """Expire breaks/temporary exits and close sessions whose tracking window has ended (incomplete)."""
    stats = {"breaks_expired": 0, "incomplete": 0}
    live = db.scalars(select(AttendanceSession).where(AttendanceSession.status.in_([SessionStatus.OPEN, SessionStatus.AWAY]))).all()
    for s in live:
        stats["breaks_expired"] += att.expire_due_breaks(db, s.employee_id, now, now)
    db.flush()
    live = db.scalars(select(AttendanceSession).where(AttendanceSession.status.in_([SessionStatus.OPEN, SessionStatus.AWAY]))).all()
    for s in live:
        settings = att.org_settings(db, s.organization_id)
        rec = s.record
        # End of the shift (or of the unscheduled day) + timeout. Sessions are never closed because GPS went quiet
        # during the shift: only shift end + timeout, or the maximum-absence rule handled above, close them.
        end = rec.scheduled_end or day_bounds_utc(rec.work_date, rec.timezone)[1]
        limit = settings.post_shift_tracking_minutes
        if settings.automatic_attendance:
            limit = min(limit, settings.automatic_checkout_timeout_minutes)
        if now > end + timedelta(minutes=limit):
            att.close_after_tracking_window(db, s, now)
            att.recompute(db, rec, now)
            stats["incomplete"] += 1
    db.commit()
    return stats


def finalize_days(db: Session, now: datetime) -> int:
    """After each shift's tracking window: final status (ABSENT only with signal, else LOCATION_UNAVAILABLE)."""
    n = 0
    for org in _orgs(db):
        settings = att.org_settings(db, org.id)
        for emp in _employees(db, org.id):
            today = local_date(now, org.timezone)
            for offset in (-2, -1, 0):
                shift = shift_for_date(db, emp, today + timedelta(days=offset), settings)
                if shift is None or now <= shift.window_end:
                    continue
                rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.work_date == shift.work_date))
                if rec is not None and rec.is_finalized:
                    continue
                att.finalize_day(db, emp, shift, now)
                n += 1
    db.commit()
    return n


def recalculate_open_records(db: Session, now: datetime) -> int:
    """Refresh live working-duration figures for records with live sessions."""
    recs = db.scalars(select(AttendanceRecord).join(AttendanceSession).where(AttendanceSession.status.in_([SessionStatus.OPEN, SessionStatus.AWAY])).distinct()).all()
    for r in recs:
        att.recompute(db, r, now)
    db.commit()
    return len(recs)


def remind_pending_confirmations(db: Session, now: datetime) -> int:
    n = 0
    for org in _orgs(db):
        settings = att.org_settings(db, org.id)
        cutoff = now - timedelta(minutes=settings.confirmation_reminder_minutes)
        sessions = db.scalars(select(AttendanceSession).where(
            AttendanceSession.organization_id == org.id,
            (AttendanceSession.confirmation == SessionConfirmation.PENDING) | (AttendanceSession.status == SessionStatus.PENDING_CHECKOUT),
            AttendanceSession.reminder_sent_at.is_(None), AttendanceSession.updated_at <= cutoff)).all()
        for s in sessions:
            emp = db.get(Employee, s.employee_id)
            if emp is None:
                continue
            what = "arrival" if s.confirmation == SessionConfirmation.PENDING else "checkout"
            notify_employee(db, emp, type="CONFIRMATION_REMINDER", title=f"Please confirm your {what}",
                            body=f"Your {what} is still awaiting confirmation.", data={"record_id": s.record_id, "session_id": s.id})
            s.reminder_sent_at = now
            n += 1
    db.commit()
    return n


def notify_hr_anomalies(db: Session, now: datetime) -> int:
    rows = db.scalars(select(AttendanceAnomaly).where(AttendanceAnomaly.hr_notified_at.is_(None),
                                                      AttendanceAnomaly.severity.in_([AnomalySeverity.WARNING, AnomalySeverity.HIGH]))).all()
    by_org: dict[int, list[AttendanceAnomaly]] = {}
    for a in rows:
        by_org.setdefault(a.organization_id, []).append(a)
    for org_id, items in by_org.items():
        depts = {}
        for a in items:
            emp = db.get(Employee, a.employee_id)
            depts.setdefault(emp.department_id if emp else None, []).append(a)
        for dept_id, group in depts.items():
            notify_hr(db, org_id, dept_id, type="ANOMALIES", title=f"{len(group)} attendance anomalies to review",
                      body=", ".join(sorted({a.type.value for a in group})) + ". Review before taking any action.",
                      data={"anomaly_ids": [a.id for a in group]})
        for a in items:
            a.hr_notified_at = now
    db.commit()
    return len(rows)


def generate_reports(db: Session, now: datetime, report_type: ReportType) -> int:
    """Snapshot the previous complete period per org (org timezone). Idempotent via unique constraint."""
    n = 0
    for org in _orgs(db):
        today = local_date(now, org.timezone)
        if report_type == ReportType.DAILY:
            start = end = today - timedelta(days=1)
            data = reports.daily(db, org.id, start)
        elif report_type == ReportType.WEEKLY:
            start, end = reports.week_bounds(today - timedelta(days=7))
            data = reports.period_summary(db, org.id, start, end)
        else:
            start, end = reports.month_bounds(today.replace(day=1) - timedelta(days=1))
            data = reports.period_summary(db, org.id, start, end)
        snap = db.scalar(select(ReportSnapshot).where(ReportSnapshot.organization_id == org.id, ReportSnapshot.report_type == report_type, ReportSnapshot.period_start == start))
        if snap is None:
            db.add(ReportSnapshot(organization_id=org.id, report_type=report_type, period_start=start, period_end=end, data=data, generated_at=now))
            notify_hr(db, org.id, None, type="REPORT_READY", title=f"{report_type.value.title()} attendance report ready",
                      body=f"Period {start.isoformat()} – {end.isoformat()}", data={"report_type": report_type.value, "period_start": start.isoformat()})
            n += 1
        else:
            snap.data, snap.generated_at = data, now  # late corrections/offline sync refresh the snapshot
    db.commit()
    return n


def purge_old_coordinates(db: Session, now: datetime) -> int:
    """Privacy retention: drop raw coordinates after the org's retention period (derived audit fields remain)."""
    total = 0
    for org in _orgs(db):
        settings = att.org_settings(db, org.id)
        cutoff = now - timedelta(days=settings.location_retention_days)
        res = db.execute(update(LocationEvent).where(LocationEvent.organization_id == org.id, LocationEvent.recorded_at < cutoff,
                                                     LocationEvent.coordinates_purged.is_(False))
                         .values(latitude=None, longitude=None, coordinates_purged=True))
        total += res.rowcount or 0
    db.commit()
    return total


def process_delayed_events(db: Session, now: datetime) -> dict[str, int]:
    return location_service.reprocess_pending(db, now)


def _already_notified(db: Session, user_id: int, type_: str, since: datetime) -> bool:
    from app.models import Notification

    return bool(db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.type == type_, Notification.created_at >= since).limit(1)))


def send_attendance_reminders(db: Session, now: datetime) -> dict[str, int]:
    """Check-in reminder shortly before shift start; check-out reminder once the shift has ended."""
    stats = {"check_in": 0, "check_out": 0}
    for org in _orgs(db):
        settings = att.org_settings(db, org.id)
        if settings.checkin_reminder_minutes <= 0:
            continue
        lead = timedelta(minutes=settings.checkin_reminder_minutes)
        for emp in _employees(db, org.id):
            today = local_date(now, org.timezone)
            for offset in (0, -1):
                shift = shift_for_date(db, emp, today + timedelta(days=offset), settings)
                if shift is None:
                    continue
                live = att.live_session(db, emp.id)
                if shift.start - lead <= now <= shift.start + timedelta(minutes=shift.grace_period_minutes) and live is None \
                        and not att.has_leave(db, emp.id, shift.start, shift.end) and not _already_notified(db, emp.user_id, "CHECKIN_REMINDER", shift.start - lead):
                    notify_employee(db, emp, type="CHECKIN_REMINDER", title="Your shift starts soon",
                                    body="Open GeoAttend at the office and tap Check in.", data={"work_date": shift.work_date.isoformat()})
                    stats["check_in"] += 1
                if live is not None and live.status == SessionStatus.OPEN and live.record.work_date == shift.work_date \
                        and shift.end + timedelta(minutes=15) <= now <= shift.window_end and not _already_notified(db, emp.user_id, "CHECKOUT_REMINDER", shift.end):
                    notify_employee(db, emp, type="CHECKOUT_REMINDER", title="Don't forget to check out",
                                    body="Your shift has ended. Check out when you leave the office.", data={"record_id": live.record_id})
                    stats["check_out"] += 1
    db.commit()
    return stats


def detect_suspicious_location_events(db: Session, now: datetime) -> int:
    from app.services.checkin_service import detect_repeated_failures

    return detect_repeated_failures(db, now)



def detect_stale_presence(db: Session, now: datetime) -> int:
    """Live sessions whose employee stopped sending location checks (tab closed / offline / GPS off).
    Informational only: the session is kept, nothing is checked out. One anomaly per employee per day."""
    from app.services.presence_service import resolve

    n = 0
    live = db.scalars(select(AttendanceSession).where(AttendanceSession.status.in_([SessionStatus.OPEN, SessionStatus.AWAY]))).all()
    for s in live:
        emp = db.get(Employee, s.employee_id)
        settings = att.org_settings(db, s.organization_id)
        if emp is None or not settings.automatic_attendance:
            continue
        v = resolve(db, emp, now, settings=settings)
        threshold = timedelta(seconds=settings.presence_stale_seconds * 5)
        if v.zone_status in ("STALE", "UNKNOWN", "LOCATION_DENIED") and (v.last_activity is None or now - v.last_activity > threshold):
            if raise_anomaly(db, org_id=s.organization_id, employee_id=s.employee_id, type=AnomalyType.LOCATION_STALE, severity=AnomalySeverity.INFO,
                             record_id=s.record_id, work_date=s.record.work_date,
                             details={"session_id": s.id, "zone_status": v.zone_status,
                                      "last_activity": v.last_activity.isoformat() if v.last_activity else None,
                                      "note": "Session kept; no automatic checkout without reliable evidence."}):
                n += 1
    db.commit()
    return n
