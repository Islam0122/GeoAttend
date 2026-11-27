"""Domain enumerations (stored as VARCHAR + CHECK for portability)."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    HR = "HR"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"
    ACCOUNTANT = "ACCOUNTANT"


class SubscriptionPlan(StrEnum):
    FREE = "FREE"
    STARTER = "STARTER"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class CompanyType(StrEnum):
    IT = "IT"
    EDUCATION = "EDUCATION"
    SMALL_BUSINESS = "SMALL_BUSINESS"
    MEDIUM_BUSINESS = "MEDIUM_BUSINESS"
    ENTERPRISE = "ENTERPRISE"
    OTHER = "OTHER"


class EmploymentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    ON_LEAVE = "ON_LEAVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LocationEventType(StrEnum):
    PRESENCE = "PRESENCE"        # periodic check while the attendance screen is open
    CHECK_IN = "CHECK_IN"        # explicit employee action
    CHECK_OUT = "CHECK_OUT"      # explicit employee action


class AttendanceMode(StrEnum):
    MANUAL = "MANUAL"          # employee presses Check-in / Check-out (explicit GPS validation)
    AUTOMATIC = "AUTOMATIC"    # server opens/closes sessions from confirmed geofence transitions
    HYBRID = "HYBRID"          # automatic detection + manual actions allowed


class DetectionMethod(StrEnum):
    AUTOMATIC = "AUTOMATIC"    # confirmed geofence transition (presence checks)
    MANUAL = "MANUAL"          # employee pressed a button (GPS-validated) or started a break
    CORRECTION = "CORRECTION"  # admin/HR correction or override
    SYSTEM = "SYSTEM"          # scheduled job (timeout, shift end)


class AttendanceEffect(StrEnum):
    AUTO_CHECKIN = "AUTO_CHECKIN"
    TEMPORARY_EXIT = "TEMPORARY_EXIT"
    RETURN_TO_OFFICE = "RETURN_TO_OFFICE"
    FINAL_CHECKOUT = "FINAL_CHECKOUT"
    OFFICE_SWITCH = "OFFICE_SWITCH"
    IGNORED_OVERLAP = "IGNORED_OVERLAP"          # inside another assigned office already holding the session
    CHECKIN_DISABLED = "CHECKIN_DISABLED"
    CHECKOUT_DISABLED = "CHECKOUT_DISABLED"
    NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
    PRESENCE_ONLY = "PRESENCE_ONLY"              # manual mode: transitions update presence only


class ConfirmationPolicy(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    EMPLOYEE_CONFIRMATION = "EMPLOYEE_CONFIRMATION"
    MANAGER_APPROVAL = "MANAGER_APPROVAL"


class CheckoutPolicy(StrEnum):
    AUTO_CLOSE = "AUTO_CLOSE"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"


class Platform(StrEnum):
    ANDROID = "ANDROID"
    IOS = "IOS"
    WEB = "WEB"


class PermissionStatus(StrEnum):
    GRANTED_ALWAYS = "GRANTED_ALWAYS"
    GRANTED_WHEN_IN_USE = "GRANTED_WHEN_IN_USE"
    DENIED = "DENIED"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class EventTrigger(StrEnum):
    GEOFENCE_ENTER = "GEOFENCE_ENTER"
    GEOFENCE_EXIT = "GEOFENCE_EXIT"
    PERIODIC = "PERIODIC"
    FOREGROUND = "FOREGROUND"
    MANUAL = "MANUAL"


class Zone(StrEnum):
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    UNCERTAIN = "UNCERTAIN"


class GeofencePresence(StrEnum):
    UNKNOWN = "UNKNOWN"
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"


class EventProcessingStatus(StrEnum):
    PENDING = "PENDING"            # stored, processing deferred/failed -> retried by task
    ACCEPTED = "ACCEPTED"          # applied to the geofence state machine
    LOW_ACCURACY = "LOW_ACCURACY"  # stored, accuracy too poor to decide (UNCERTAIN)
    OUT_OF_ORDER = "OUT_OF_ORDER"  # older than the last applied reading; kept for audit only
    SUSPICIOUS = "SUSPICIOUS"      # spoofing indicator; excluded from attendance, sent to review
    NO_OFFICE = "NO_OFFICE"        # no active geofence to evaluate against


class TransitionType(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class AttendanceStatus(StrEnum):
    PRESENT = "PRESENT"
    LATE = "LATE"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    INCOMPLETE = "INCOMPLETE"
    ON_LEAVE = "ON_LEAVE"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE"
    UNSCHEDULED = "UNSCHEDULED"   # attendance without a scheduled shift (policy: allow_unscheduled_attendance)


class SessionStatus(StrEnum):
    OPEN = "OPEN"                        # employee inside office
    AWAY = "AWAY"                        # on break / temporary exit / business trip
    PENDING_CHECKOUT = "PENDING_CHECKOUT"  # exit detected; waiting for employee confirmation
    CLOSED = "CLOSED"


class SessionConfirmation(StrEnum):
    AUTO_CONFIRMED = "AUTO_CONFIRMED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"   # invalidated (employee rejected or approved dispute)


class SessionSource(StrEnum):
    GPS = "GPS"
    MANUAL = "MANUAL"
    CORRECTION = "CORRECTION"


class CloseReason(StrEnum):
    GEOFENCE_EXIT = "GEOFENCE_EXIT"
    TEMPORARY_EXIT_EXPIRED = "TEMPORARY_EXIT_EXPIRED"
    BREAK_NOT_RETURNED = "BREAK_NOT_RETURNED"
    BUSINESS_TRIP_END = "BUSINESS_TRIP_END"
    TRACKING_WINDOW_ENDED = "TRACKING_WINDOW_ENDED"
    OFFICE_SWITCH = "OFFICE_SWITCH"
    CORRECTION = "CORRECTION"
    MANUAL = "MANUAL"
    EMPLOYEE_CHECKOUT = "EMPLOYEE_CHECKOUT"


class BreakType(StrEnum):
    LUNCH = "LUNCH"
    TEMPORARY_EXIT = "TEMPORARY_EXIT"
    BUSINESS_TRIP = "BUSINESS_TRIP"
    PERSONAL = "PERSONAL"
    MEETING = "MEETING"


class BreakOutcome(StrEnum):
    OPEN = "OPEN"                    # employee is currently away
    RETURNED = "RETURNED"            # came back; session resumed
    NOT_RETURNED = "NOT_RETURNED"    # max absence exceeded; session ended at the exit time
    SESSION_CLOSED = "SESSION_CLOSED"  # session closed while away (shift end / checkout / correction)


class AbsenceType(StrEnum):
    LEAVE = "LEAVE"
    SICK = "SICK"
    BUSINESS_TRIP = "BUSINESS_TRIP"


class RequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CorrectionType(StrEnum):
    DISPUTE = "DISPUTE"
    MISSING_CHECK_IN = "MISSING_CHECK_IN"
    MISSING_CHECK_OUT = "MISSING_CHECK_OUT"
    WRONG_TIME = "WRONG_TIME"
    OTHER = "OTHER"


class AnomalyType(StrEnum):
    MOCK_LOCATION = "MOCK_LOCATION"
    IMPOSSIBLE_SPEED = "IMPOSSIBLE_SPEED"
    UNREGISTERED_DEVICE = "UNREGISTERED_DEVICE"
    SHARED_DEVICE = "SHARED_DEVICE"
    MULTIPLE_DEVICES = "MULTIPLE_DEVICES"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    MISSING_CHECK_IN = "MISSING_CHECK_IN"
    INCOMPLETE_SESSION = "INCOMPLETE_SESSION"
    LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    DELAYED_SYNC = "DELAYED_SYNC"
    LOCATION_STALE = "LOCATION_STALE"
    REPEATED_FAILED_CHECKIN = "REPEATED_FAILED_CHECKIN"


class AnomalySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


class AnomalyStatus(StrEnum):
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    DISMISSED = "DISMISSED"


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ReportType(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
