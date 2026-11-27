from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import EventTrigger, PermissionStatus, Platform
from app.schemas.common import ORMModel


class LocationEventIn(BaseModel):
    """Raw fix from a device. Range checks happen server-side in the engine so that batches
    can reject individual items instead of failing as a whole. Distance/zone/status are never accepted."""

    client_event_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-:.]+$")
    device_id: str = Field(min_length=4, max_length=128)
    latitude: float
    longitude: float
    accuracy: float
    recorded_at: datetime
    platform: Platform
    permission_status: PermissionStatus
    trigger: EventTrigger = EventTrigger.PERIODIC
    is_mocked: bool = False


class LocationBatchIn(BaseModel):
    events: list[dict] = Field(min_length=1, max_length=500)


class EventResultOut(BaseModel):
    client_event_id: str | None
    result: str
    reason: str | None = None
    event_id: int | None = None
    office_id: int | None = None
    distance_m: float | None = None
    accuracy_m: float | None = None
    zone: str | None = None
    transition: str | None = None
    attendance_status: str | None = None
    session_id: int | None = None
    work_date: str | None = None
    errors: list[dict] | None = None


class BatchResultOut(BaseModel):
    results: list[EventResultOut]
    accepted: int
    duplicates: int
    rejected: int


class LocationHistoryOut(ORMModel):
    id: int
    client_event_id: str
    recorded_at: datetime
    received_at: datetime
    latitude: float | None
    longitude: float | None
    accuracy_m: float
    office_id: int | None
    distance_m: float | None
    zone: str | None
    processing_status: str
    status_reason: str | None
    transition: str | None
    trigger: str
    work_date: date | None


class OfficeFence(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    radius_m: float
    max_accuracy_m: float
    timezone: str


class TrackingWindow(BaseModel):
    work_date: date
    start: datetime
    end: datetime
    shift_start: datetime
    shift_end: datetime
    active: bool


class MyLocationStatus(BaseModel):
    employee_id: int
    employee_name: str
    consent_granted: bool
    consent_version_required: str
    device_registered: bool
    location_permission: str | None
    tracking_active: bool
    tracking_window: TrackingWindow | None
    offices: list[OfficeFence]
    presence: str
    office_id: int | None
    last_zone: str | None
    distance_m: float | None
    accuracy_m: float | None
    last_update: datetime | None
    session_status: str | None
    server_time: datetime


class DeviceRegisterIn(BaseModel):
    device_id: str = Field(min_length=4, max_length=128)
    platform: Platform
    model: str | None = Field(default=None, max_length=120)
    os_version: str | None = Field(default=None, max_length=40)
    app_version: str | None = Field(default=None, max_length=40)
    push_token: str | None = Field(default=None, max_length=255)
    location_permission: PermissionStatus = PermissionStatus.UNKNOWN
    precise_location: bool = True
    background_enabled: bool = False


class DeviceHeartbeatIn(BaseModel):
    device_id: str = Field(min_length=4, max_length=128)
    location_permission: PermissionStatus
    precise_location: bool = True
    background_enabled: bool = False
    push_token: str | None = Field(default=None, max_length=255)


class DeviceOut(ORMModel):
    id: int
    device_id: str
    platform: Platform
    model: str | None
    os_version: str | None
    app_version: str | None
    location_permission: PermissionStatus
    precise_location: bool
    background_enabled: bool
    last_seen_at: datetime | None
    is_active: bool


class ConsentIn(BaseModel):
    granted: bool
    consent_version: str = Field(min_length=1, max_length=20)


class ConsentOut(BaseModel):
    granted: bool
    consent_version: str | None
    updated_at: datetime | None
    required_version: str
    policy_text: str


class MonitoringRow(BaseModel):
    employee_id: int
    employee_name: str
    department_name: str | None
    office_id: int | None
    office_name: str | None
    presence: str
    last_zone: str | None
    distance_m: float | None
    accuracy_m: float | None
    last_update: datetime | None
    is_fresh: bool
    location_permission: str | None
    consent_granted: bool
    session_status: str | None


class UncertainEventOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    office_id: int | None
    distance_m: float | None
    accuracy_m: float
    recorded_at: datetime
    processing_status: str
    status_reason: str | None
