"""All ORM models (imported here so metadata is complete for Alembic)."""
from app.models.attendance import (
    AttendanceAnomaly,
    AttendanceBreak,
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSession,
)
from app.models.location import (
    DeviceRegistration,
    GeofenceState,
    GeofenceTransition,
    LocationConsent,
    LocationEvent,
)
from app.models.office import Office, OfficeAssignment, OfficeGeofence
from app.models.organization import (
    Department,
    Employee,
    ManagerDepartment,
    Organization,
    OrganizationSettings,
    RefreshToken,
    User,
)
from app.models.schedule import (
    AbsencePeriod,
    LeaveRequest,
    ScheduleAssignment,
    ScheduleDay,
    WorkSchedule,
)
from app.models.system import AuditLog, Notification, ReportSnapshot

__all__ = [
    "AbsencePeriod", "AttendanceAnomaly", "AttendanceBreak", "AttendanceCorrection", "AttendanceRecord", "AttendanceSession", "AuditLog",
    "Department", "DeviceRegistration", "Employee", "GeofenceState", "GeofenceTransition", "LeaveRequest", "LocationConsent", "LocationEvent",
    "ManagerDepartment", "Notification", "Office", "OfficeAssignment", "OfficeGeofence", "Organization", "OrganizationSettings", "RefreshToken",
    "ReportSnapshot", "ScheduleAssignment", "ScheduleDay", "User", "WorkSchedule",
]
