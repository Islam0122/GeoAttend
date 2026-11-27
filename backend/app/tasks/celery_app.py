"""Celery application + beat schedule. Jobs run frequently and decide per-organization/per-shift
(using each organization's/employee's timezone) whether there is work to do; all jobs are idempotent."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("geoattend", broker=s.celery_broker_url, backend=s.celery_result_backend, include=["app.tasks.jobs"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "process-delayed-gps-events": {"task": "geoattend.process_delayed_events", "schedule": 60.0},
        "deliver-notifications": {"task": "geoattend.deliver_notifications", "schedule": 30.0},
        # Automatic attendance: breaks/temporary exits and closure timeouts are resolved every minute.
        "close-expired-attendance-sessions": {"task": "geoattend.CloseExpiredAttendanceSessions", "schedule": 60.0},
        "calculate-attendance-durations": {"task": "geoattend.CalculateAttendanceDurations", "schedule": 120.0},
        "detect-stale-presence": {"task": "geoattend.DetectStalePresence", "schedule": 300.0},
        "detect-missing-checkins": {"task": "geoattend.detect_missing_checkins", "schedule": 300.0},
        "finalize-daily-attendance": {"task": "geoattend.FinalizeDailyAttendance", "schedule": 600.0},
        "remind-confirmations": {"task": "geoattend.remind_pending_confirmations", "schedule": 300.0},
        "attendance-reminders": {"task": "geoattend.send_attendance_reminders", "schedule": 120.0},
        "detect-suspicious-location": {"task": "geoattend.detect_suspicious_location_events", "schedule": 600.0},
        "notify-hr-anomalies": {"task": "geoattend.notify_hr_anomalies", "schedule": 900.0},
        # Report jobs run hourly; each org gets its snapshot once its local period has completed.
        "generate-attendance-summary": {"task": "geoattend.GenerateAttendanceSummary", "schedule": crontab(minute=15)},
        "weekly-reports": {"task": "geoattend.generate_weekly_reports", "schedule": crontab(minute=20)},
        "monthly-reports": {"task": "geoattend.generate_monthly_reports", "schedule": crontab(minute=25)},
        "purge-coordinates": {"task": "geoattend.purge_old_coordinates", "schedule": crontab(minute=40, hour="*/6")},
    },
)
