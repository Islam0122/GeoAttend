from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
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
from app.models.enums import (
    EventProcessingStatus,
    EventTrigger,
    GeofencePresence,
    LocationEventType,
    PermissionStatus,
    Platform,
    TransitionType,
    Zone,
)
from app.models.mixins import IdMixin, OrgScopedMixin, TimestampMixin, str_enum


class DeviceRegistration(IdMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "device_registrations"
    __table_args__ = (UniqueConstraint("employee_id", "device_id"),)

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    platform: Mapped[Platform] = mapped_column(str_enum(Platform), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_permission: Mapped[PermissionStatus] = mapped_column(str_enum(PermissionStatus), default=PermissionStatus.UNKNOWN, nullable=False)
    precise_location: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    background_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    permission_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LocationConsent(IdMixin, OrgScopedMixin, Base):
    """Append-only consent history. The latest row is the current state."""

    __tablename__ = "location_consents"
    __table_args__ = (Index("ix_location_consents_emp_time", "employee_id", "created_at"),)

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class LocationEvent(IdMixin, OrgScopedMixin, Base):
    """One GPS fix reported by a device. Server-side derived fields are never taken from the client."""

    __tablename__ = "location_events"
    __table_args__ = (
        UniqueConstraint("employee_id", "client_event_id"),
        Index("ix_location_events_emp_recorded", "employee_id", "recorded_at"),
        Index("ix_location_events_org_received", "organization_id", "received_at"),
        Index("ix_location_events_emp_type_time", "employee_id", "event_type", "recorded_at"),
    )

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    device_registration_id: Mapped[int | None] = mapped_column(ForeignKey("device_registrations.id", ondelete="SET NULL"), nullable=True)
    client_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[Platform] = mapped_column(str_enum(Platform), nullable=False)
    permission_status: Mapped[PermissionStatus] = mapped_column(str_enum(PermissionStatus), nullable=False)
    trigger: Mapped[EventTrigger] = mapped_column(str_enum(EventTrigger), nullable=False)
    event_type: Mapped[LocationEventType] = mapped_column(str_enum(LocationEventType), default=LocationEventType.PRESENCE, nullable=False)
    # Coordinates are nullable so the retention job can purge them while keeping the derived audit trail.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float] = mapped_column(Float, nullable=False)
    is_mocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    # Server-computed
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone: Mapped[Zone | None] = mapped_column(str_enum(Zone), nullable=True)
    processing_status: Mapped[EventProcessingStatus] = mapped_column(str_enum(EventProcessingStatus), default=EventProcessingStatus.PENDING, nullable=False, index=True)
    status_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transition: Mapped[TransitionType | None] = mapped_column(str_enum(TransitionType), nullable=True)
    work_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coordinates_purged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GeofenceState(IdMixin, OrgScopedMixin, Base):
    """Per (employee, office) hysteresis state machine."""

    __tablename__ = "geofence_states"
    __table_args__ = (UniqueConstraint("employee_id", "office_id"), Index("ix_geofence_states_emp_validated", "employee_id", "last_validated_at"))

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id", ondelete="CASCADE"), nullable=False, index=True)
    presence: Mapped[GeofencePresence] = mapped_column(str_enum(GeofencePresence), default=GeofencePresence.UNKNOWN, nullable=False)
    candidate: Mapped[GeofencePresence | None] = mapped_column(str_enum(GeofencePresence), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_since: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    candidate_first_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_inside_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_zone: Mapped[Zone | None] = mapped_column(str_enum(Zone), nullable=True)
    last_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Latest *server-validated* reading for this office (ACCEPTED event, zone INSIDE or OUTSIDE).
    # Monitoring reads these; the hysteresis fields above only drive automatic attendance.
    last_validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_validated_zone: Mapped[Zone | None] = mapped_column(str_enum(Zone), nullable=True)
    last_validated_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_validated_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_event_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class GeofenceTransition(IdMixin, OrgScopedMixin, Base):
    """A confirmed (stable) ENTER/EXIT. occurred_at = first reading of the stable streak."""

    __tablename__ = "geofence_transitions"
    __table_args__ = (Index("ix_geofence_transitions_emp_time", "employee_id", "occurred_at"),)

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[TransitionType] = mapped_column(str_enum(TransitionType), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    first_event_id: Mapped[int | None] = mapped_column(ForeignKey("location_events.id", ondelete="SET NULL"), nullable=True)
    confirming_event_id: Mapped[int | None] = mapped_column(ForeignKey("location_events.id", ondelete="SET NULL"), nullable=True)
    readings: Mapped[int] = mapped_column(Integer, nullable=False)
    attendance_effect: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
