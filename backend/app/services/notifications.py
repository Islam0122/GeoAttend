"""In-app notifications + push delivery via transactional outbox (Notification.push_status)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Employee, Notification, User
from app.models.enums import DeliveryStatus, Role

log = logging.getLogger("geoattend.notifications")


def notify(db: Session, *, org_id: int, user_id: int, type: str, title: str, body: str, data: dict | None = None) -> Notification:
    n = Notification(organization_id=org_id, user_id=user_id, type=type, title=title, body=body, data=data or {})
    db.add(n)
    return n


def notify_employee(db: Session, employee: Employee, **kw) -> Notification:
    return notify(db, org_id=employee.organization_id, user_id=employee.user_id, **kw)


def notify_hr(db: Session, org_id: int, department_id: int | None, **kw) -> list[Notification]:
    """HR/admins of the org + managers of the department."""
    users = db.scalars(select(User).where(User.organization_id == org_id, User.is_active.is_(True),
                                          User.role.in_([Role.OWNER, Role.ADMIN, Role.HR, Role.MANAGER]))).all()
    out = []
    for u in users:
        if u.role == Role.MANAGER and department_id not in {d.id for d in u.managed_departments}:
            continue
        out.append(notify(db, org_id=org_id, user_id=u.id, **kw))
    return out


# Notification types also delivered by e-mail (when SMTP is configured). Everything is always available in-app.
EMAIL_TYPES = {"CHECKIN_REMINDER", "CHECKOUT_REMINDER", "MISSING_CHECK_IN", "CORRECTION_REVIEWED", "ABSENCE_REVIEWED", "REPORT_READY",
               "ANOMALIES", "ATTENDANCE_REVIEWED", "CONSENT_WITHDRAWN"}
MAX_ATTEMPTS = 5


def deliver_pending(db: Session, limit: int = 200) -> dict[str, int]:
    """Transactional outbox: deliver PENDING notifications by e-mail. Idempotent; retried up to MAX_ATTEMPTS.
    (Web Push is not implemented; the PWA polls in-app notifications.)"""
    settings = get_settings()
    stats = {"sent": 0, "skipped": 0, "failed": 0}
    pending = db.scalars(select(Notification).where(Notification.push_status == DeliveryStatus.PENDING).order_by(Notification.id).limit(limit)).all()
    for n in pending:
        user = db.get(User, n.user_id)
        if not settings.smtp_host or n.type not in EMAIL_TYPES or user is None or not user.is_active:
            n.push_status = DeliveryStatus.SKIPPED
            stats["skipped"] += 1
            continue
        n.push_attempts += 1
        if send_email(user.email, n.title, f"{n.body}\n\n{settings.frontend_url}"):
            n.push_status = DeliveryStatus.SENT
            stats["sent"] += 1
        else:
            if n.push_attempts >= MAX_ATTEMPTS:
                n.push_status = DeliveryStatus.FAILED
            stats["failed"] += 1
    db.commit()
    return stats


def send_email(to: str, subject: str, body: str) -> bool:
    settings = get_settings()
    if not settings.smtp_host:
        log.info("email_not_configured", extra={"to_domain": to.split("@")[-1], "subject": subject})
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            if settings.smtp_tls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password or "")
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("email_failed", extra={"error": str(exc)})
        return False
