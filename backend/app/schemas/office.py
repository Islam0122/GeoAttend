from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.timeutils import is_valid_timezone
from app.schemas.common import ORMModel


class GeofenceOut(ORMModel):
    radius_m: float
    max_accuracy_m: float
    enabled: bool
    entry_detection_enabled: bool
    exit_detection_enabled: bool
    required_consecutive: int
    stability_window_seconds: int
    entry_buffer_m: float
    exit_buffer_m: float
    updated_at: datetime


class GeofencePatch(BaseModel):
    radius_m: float | None = Field(default=None, ge=10, le=5000)
    max_accuracy_m: float | None = Field(default=None, gt=0, le=1000)
    enabled: bool | None = None
    entry_detection_enabled: bool | None = None
    exit_detection_enabled: bool | None = None
    required_consecutive: int | None = Field(default=None, ge=1, le=20)
    stability_window_seconds: int | None = Field(default=None, ge=0, le=3600)
    entry_buffer_m: float | None = Field(default=None, ge=0, le=500)
    exit_buffer_m: float | None = Field(default=None, ge=0, le=500)


def _tz(v: str | None) -> str | None:
    if v is not None and not is_valid_timezone(v):
        raise ValueError("Unknown IANA timezone")
    return v


class OfficeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=300)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str | None = None
    is_active: bool = True
    radius: float | None = Field(default=None, ge=10, le=5000, description="Geofence radius in metres")
    max_accuracy: float | None = Field(default=None, gt=0, le=1000, description="Maximum acceptable GPS accuracy in metres")
    geofence: GeofencePatch | None = None
    employee_ids: list[int] = []

    _v_tz = field_validator("timezone")(_tz)


class OfficePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = None
    is_active: bool | None = None
    radius: float | None = Field(default=None, ge=10, le=5000)
    max_accuracy: float | None = Field(default=None, gt=0, le=1000)
    employee_ids: list[int] | None = None

    _v_tz = field_validator("timezone")(_tz)


class OfficeOut(ORMModel):
    id: int
    name: str
    address: str | None
    latitude: float
    longitude: float
    timezone: str
    is_active: bool
    radius: float
    max_accuracy: float
    geofence: GeofenceOut
    employee_ids: list[int]
    created_at: datetime
