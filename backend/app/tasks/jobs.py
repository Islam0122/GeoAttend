from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.core import db as dbmod
from app.core.timeutils import utcnow
from app.models.enums import ReportType
from app.services import automation
from app.services.notifications import deliver_pending
from app.tasks.celery_app import celery_app

log = logging.getLogger("geoattend.tasks")


def _run(name: str, fn: Callable[..., Any], *args: Any) -> Any:
    with dbmod.SessionLocal() as db:
        result = fn(db, utcnow(), *args)
        log.info("task_done", extra={"task": name, "result": result})
        return result


@celery_app.task(name="geoattend.process_delayed_events", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_delayed_events():
    return _run("process_delayed_events", automation.process_delayed_events)


@celery_app.task(name="geoattend.deliver_notifications", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def deliver_notifications():
    with dbmod.SessionLocal() as db:
        return deliver_pending(db)


@celery_app.task(name="geoattend.resolve_sessions")
def resolve_sessions():
    return _run("resolve_sessions", automation.resolve_sessions)


@celery_app.task(name="geoattend.recalculate_open_records")
def recalculate_open_records():
    return _run("recalculate_open_records", automation.recalculate_open_records)


@celery_app.task(name="geoattend.detect_missing_checkins")
def detect_missing_checkins():
    return _run("detect_missing_checkins", automation.detect_missing_checkins)


@celery_app.task(name="geoattend.finalize_days")
def finalize_days():
    return _run("finalize_days", automation.finalize_days)


@celery_app.task(name="geoattend.remind_pending_confirmations")
def remind_pending_confirmations():
    return _run("remind_pending_confirmations", automation.remind_pending_confirmations)


@celery_app.task(name="geoattend.notify_hr_anomalies")
def notify_hr_anomalies():
    return _run("notify_hr_anomalies", automation.notify_hr_anomalies)


@celery_app.task(name="geoattend.generate_daily_reports")
def generate_daily_reports():
    return _run("generate_daily_reports", automation.generate_reports, ReportType.DAILY)


@celery_app.task(name="geoattend.generate_weekly_reports")
def generate_weekly_reports():
    return _run("generate_weekly_reports", automation.generate_reports, ReportType.WEEKLY)


@celery_app.task(name="geoattend.generate_monthly_reports")
def generate_monthly_reports():
    return _run("generate_monthly_reports", automation.generate_reports, ReportType.MONTHLY)


@celery_app.task(name="geoattend.purge_old_coordinates")
def purge_old_coordinates():
    return _run("purge_old_coordinates", automation.purge_old_coordinates)


@celery_app.task(name="geoattend.send_attendance_reminders")
def send_attendance_reminders():
    return _run("send_attendance_reminders", automation.send_attendance_reminders)


@celery_app.task(name="geoattend.detect_suspicious_location_events")
def detect_suspicious_location_events():
    return _run("detect_suspicious_location_events", automation.detect_suspicious_location_events)


# ---- Automatic attendance job names (spec). Each delegates to the idempotent implementation above. ----
@celery_app.task(name="geoattend.DetectStalePresence")
def detect_stale_presence_task():
    return _run("detect_stale_presence", automation.detect_stale_presence)


@celery_app.task(name="geoattend.CloseExpiredAttendanceSessions")
def close_expired_attendance_sessions():
    return _run("close_expired_attendance_sessions", automation.resolve_sessions)


@celery_app.task(name="geoattend.CalculateAttendanceDurations")
def calculate_attendance_durations():
    return _run("calculate_attendance_durations", automation.recalculate_open_records)


@celery_app.task(name="geoattend.FinalizeDailyAttendance")
def finalize_daily_attendance():
    return _run("finalize_daily_attendance", automation.finalize_days)


@celery_app.task(name="geoattend.GenerateAttendanceSummary")
def generate_attendance_summary():
    return _run("generate_attendance_summary", automation.generate_reports, ReportType.DAILY)
