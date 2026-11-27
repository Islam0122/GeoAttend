"""Anomaly recording. Anomalies are review signals for HR; they never change attendance by themselves."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceAnomaly
from app.models.enums import AnomalySeverity, AnomalyStatus, AnomalyType

log = logging.getLogger("geoattend.anomalies")

# Anomaly types that should be raised at most once per employee per work date.
DAILY_UNIQUE = {
    AnomalyType.MISSING_CHECK_IN, AnomalyType.LOCATION_UNAVAILABLE, AnomalyType.MULTIPLE_DEVICES,
    AnomalyType.SHARED_DEVICE, AnomalyType.UNREGISTERED_DEVICE, AnomalyType.REPEATED_FAILED_CHECKIN, AnomalyType.LOCATION_STALE,
}


def raise_anomaly(db: Session, *, org_id: int, employee_id: int, type: AnomalyType, severity: AnomalySeverity,
                  location_event_id: int | None = None, record_id: int | None = None, work_date: date | None = None,
                  details: dict | None = None) -> AttendanceAnomaly | None:
    if type in DAILY_UNIQUE and work_date is not None:
        dup = db.scalar(select(AttendanceAnomaly.id).where(
            AttendanceAnomaly.employee_id == employee_id, AttendanceAnomaly.type == type, AttendanceAnomaly.work_date == work_date))
        if dup:
            return None
    a = AttendanceAnomaly(organization_id=org_id, employee_id=employee_id, type=type, severity=severity, status=AnomalyStatus.OPEN,
                          location_event_id=location_event_id, record_id=record_id, work_date=work_date, details=details or {})
    db.add(a)
    log.warning("anomaly", extra={"org_id": org_id, "employee_id": employee_id, "type": type.value, "severity": severity.value})
    return a
