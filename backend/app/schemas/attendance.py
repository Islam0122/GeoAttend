from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    AttendanceStatus,
    BreakType,
    CloseReason,
    CorrectionType,
    RequestStatus,
    SessionConfirmation,
    SessionSource,
    SessionStatus,
)
from app.schemas.common import ORMModel


class BreakOut(ORMModel):
    id: int
    type: BreakType
    is_paid: bool
    started_at: datetime
    ended_at: datetime | None
    expires_at: datetime
    detection_method: str = "AUTOMATIC"
    outcome: str = "OPEN"
    duration_minutes: int | None = None


class SessionOut(ORMModel):
    id: int
    office_id: int | None
    status: SessionStatus
    confirmation: SessionConfirmation
    source: SessionSource
    check_in_at: datetime
    detected_at: datetime | None
    confirmed_at: datetime | None
    check_out_at: datetime | None
    checkout_detected_at: datetime | None
    checkout_confirmed_at: datetime | None
    close_reason: CloseReason | None
    breaks: list[BreakOut]
    duration_minutes: int | None = None
    gross_minutes: int | None = None
    detection_method: str = "MANUAL"
    check_in_accuracy_m: float | None = None
    check_in_event_id: int | None = None
    check_out_event_id: int | None = None
    approved_by_id: int | None = None


class RecordOut(ORMModel):
    id: int
    employee_id: int
    employee_name: str | None = None
    department_name: str | None = None
    office_id: int | None
    office_name: str | None = None
    work_date: date
    timezone: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    scheduled_minutes: int
    actual_check_in: datetime | None
    actual_check_out: datetime | None
    late_minutes: int
    early_departure_minutes: int
    worked_minutes: int
    break_minutes: int
    overtime_minutes: int
    status: AttendanceStatus
    is_finalized: bool
    is_confirmed: bool = False
    early_arrival_minutes: int = 0
    presence_minutes: int = 0
    temporary_exit_minutes: int = 0
    is_unscheduled: bool = False


class RecordDetailOut(RecordOut):
    sessions: list[SessionOut]
    pending_confirmation: bool
    pending_checkout: bool


class TodayOut(BaseModel):
    work_date: date | None
    shift: dict | None
    record: RecordDetailOut | None
    location: dict
    offices: list[dict] = []
    actions: dict = {}
    server_time: datetime | None = None


class TeamTodayRow(BaseModel):
    employee_id: int
    employee_name: str
    department_name: str | None
    office_name: str | None
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    actual_check_in: datetime | None
    actual_check_out: datetime | None
    worked_minutes: int
    late_minutes: int
    status: str
    record_id: int | None
    presence: str


class DashboardOut(BaseModel):
    date: date
    total_employees: int
    scheduled_today: int
    present: int
    late: int
    missing_check_ins: int
    inside_office: int
    outside_office: int
    unconfirmed: int
    location_unavailable: int
    on_leave: int
    open_anomalies: int
    pending_corrections: int
    absent: int = 0
    avg_working_minutes: int = 0
    overtime_minutes: int = 0
    is_today: bool = True
    stale: int = 0
    active_sessions: int = 0
    temporary_exits: int = 0


class ConfirmIn(BaseModel):
    action: Literal["CONFIRM", "REJECT"] = "CONFIRM"
    session_id: int | None = None


class CorrectionIn(BaseModel):
    type: CorrectionType
    requested_check_in: datetime | None = None
    requested_check_out: datetime | None = None
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def _order(self):
        if self.requested_check_in and self.requested_check_out and self.requested_check_out <= self.requested_check_in:
            raise ValueError("requested_check_out must be after requested_check_in")
        if self.type in (CorrectionType.MISSING_CHECK_IN, CorrectionType.WRONG_TIME) and not (self.requested_check_in or self.requested_check_out):
            raise ValueError("Provide the corrected time(s)")
        if self.type == CorrectionType.MISSING_CHECK_OUT and not self.requested_check_out:
            raise ValueError("requested_check_out is required")
        return self


class CorrectionOut(ORMModel):
    id: int
    record_id: int
    employee_id: int
    employee_name: str | None = None
    work_date: date | None = None
    type: CorrectionType
    requested_check_in: datetime | None
    requested_check_out: datetime | None
    reason: str
    status: RequestStatus
    reviewed_by_id: int | None
    reviewed_at: datetime | None
    review_comment: str | None
    created_at: datetime


class AnomalyOut(ORMModel):
    id: int
    employee_id: int
    employee_name: str | None = None
    type: AnomalyType
    severity: AnomalySeverity
    status: AnomalyStatus
    work_date: date | None
    details: dict | None
    detected_at: datetime
    reviewed_at: datetime | None
    review_comment: str | None


class AnomalyReviewIn(BaseModel):
    status: Literal["REVIEWED", "DISMISSED"]
    comment: str | None = Field(default=None, max_length=2000)


class NotificationOut(ORMModel):
    id: int
    type: str
    title: str
    body: str
    data: dict | None
    read_at: datetime | None
    created_at: datetime


class AuditLogOut(ORMModel):
    id: int
    actor_user_id: int | None
    action: str
    entity_type: str
    entity_id: str | None
    changes: dict | None
    ip_address: str | None
    created_at: datetime


class GpsActionIn(BaseModel):
    """Browser Geolocation reading for an explicit check-in / check-out. Distance and status are computed server-side."""

    event_uuid: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-:.]+$")
    device_id: str = Field(min_length=4, max_length=128)
    latitude: float
    longitude: float
    accuracy: float
    recorded_at: datetime  # client time of the GPS fix (preserved for offline queue)
    permission_status: str = "GRANTED_WHEN_IN_USE"
    offline: bool = False  # set by the PWA when the action was queued while offline


class GpsActionOut(BaseModel):
    state: str
    code: str
    message: str
    client_event_id: str | None = None
    event_id: int | None = None
    office_id: int | None = None
    office_name: str | None = None
    radius_m: float | None = None
    max_accuracy_m: float | None = None
    distance_m: float | None = None
    accuracy_m: float | None = None
    zone: str | None = None
    session_id: int | None = None
    record_id: int | None = None
    attendance_status: str | None = None
    pending_approval: bool = False
    recorded_at: datetime | None = None
    received_at: datetime | None = None
    duplicate: bool = False


class BreakIn(BaseModel):
    type: Literal["LUNCH", "TEMPORARY_EXIT"] = "LUNCH"


class DisputeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    requested_check_in: datetime | None = None
    requested_check_out: datetime | None = None


class ApprovalIn(BaseModel):
    approve: bool = True
    session_id: int | None = None
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalRow(BaseModel):
    record_id: int
    session_id: int
    employee_id: int
    employee_name: str
    department_name: str | None
    work_date: date
    check_in_at: datetime
    check_out_at: datetime | None
    office_name: str | None
    timezone: str
