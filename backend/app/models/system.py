from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime
from app.core.timeutils import utcnow
from app.models.enums import DeliveryStatus, ReportType
from app.models.mixins import IdMixin, OrgScopedMixin, str_enum


class AuditLog(IdMixin, OrgScopedMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_org_time", "organization_id", "created_at"),)

    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Notification(IdMixin, OrgScopedMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_time", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    push_status: Mapped[DeliveryStatus] = mapped_column(str_enum(DeliveryStatus), default=DeliveryStatus.PENDING, nullable=False)
    push_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ReportSnapshot(IdMixin, OrgScopedMixin, Base):
    __tablename__ = "report_snapshots"
    __table_args__ = (UniqueConstraint("organization_id", "report_type", "period_start"),)

    report_type: Mapped[ReportType] = mapped_column(str_enum(ReportType), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
