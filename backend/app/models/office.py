from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.core.timeutils import utcnow
from app.models.mixins import IdMixin, OrgScopedMixin, TimestampMixin


class Office(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "offices"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="lng_range"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    geofence: Mapped[OfficeGeofence] = relationship(back_populates="office", uselist=False, cascade="all, delete-orphan", lazy="joined")


class OfficeGeofence(IdMixin, OrgScopedMixin, Base):
    """Geofence parameters + entry/exit detection (hysteresis) settings for one office."""

    __tablename__ = "office_geofences"
    __table_args__ = (
        CheckConstraint("radius_m BETWEEN 10 AND 5000", name="radius_range"),
        CheckConstraint("max_accuracy_m > 0 AND max_accuracy_m <= 1000", name="accuracy_range"),
        CheckConstraint("required_consecutive BETWEEN 1 AND 20", name="consecutive_range"),
        CheckConstraint("stability_window_seconds BETWEEN 0 AND 3600", name="window_range"),
        CheckConstraint("entry_buffer_m >= 0 AND exit_buffer_m >= 0", name="buffers_positive"),
    )

    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id", ondelete="CASCADE"), unique=True, nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    max_accuracy_m: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entry_detection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    exit_detection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required_consecutive: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    stability_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # Hysteresis: entry needs to be confirmed `entry_buffer_m` inside the radius,
    # exit needs to be confirmed `exit_buffer_m` outside it.
    entry_buffer_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    exit_buffer_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)

    office: Mapped[Office] = relationship(back_populates="geofence")


class OfficeAssignment(IdMixin, OrgScopedMixin, Base):
    __tablename__ = "office_assignments"
    __table_args__ = (UniqueConstraint("office_id", "employee_id"),)

    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
