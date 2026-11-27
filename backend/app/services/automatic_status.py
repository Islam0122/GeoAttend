"""Maps server facts to the employee-facing automatic-attendance state (with human-readable messages).

Frontend-only states (INITIALIZING, REQUESTING_PERMISSION, LOCATION_UNAVAILABLE, CONNECTION_LOST) are added by
the browser; every state below is derived exclusively from server-validated data.
"""
from __future__ import annotations

from app.models import OrganizationSettings
from app.services.presence_service import PresenceView

MESSAGES = {
    "AUTO_CHECKIN": "Your work day started automatically when you arrived at the office.",
    "SESSION_RESUMED": "Welcome back — your work session has resumed.",
    "ACTIVE_SESSION": "You are at the office and your work session is active.",
    "TEMPORARY_EXIT": "You are temporarily away from the office. Your session is kept and resumes automatically when you return.",
    "SESSION_COMPLETED": "Your work session for today is completed.",
    "UNSCHEDULED": "You have no scheduled shift today.",
    "INSIDE_GEOFENCE": "You are inside the office zone.",
    "OUTSIDE_GEOFENCE": "You are outside the office zone.",
    "GPS_INACCURATE": "GPS accuracy is too low to confirm your position. Move near a window or outdoors; we'll retry automatically.",
    "LOCATION_DETECTED": "Location received; waiting for a precise reading to confirm your zone.",
    "NO_OFFICE": "No office is assigned to you. Ask your administrator.",
    "OUTSIDE_WORKING_WINDOW": "Location checks are only performed during your scheduled working window.",
    "STALE": "Your last location check is out of date. Keep this screen open to stay up to date.",
    "UNKNOWN": "Waiting for the first location check.",
    "LOCATION_DENIED": "Location permission is blocked in your browser.",
}


def derive(view: PresenceView, settings: OrganizationSettings, *, effects: list[str] | None = None, reading: dict | None = None) -> tuple[str, str]:
    effects = effects or []
    reading = reading or {}
    reason = reading.get("reason")
    if reading.get("result") == "REJECTED" and reason == "OUTSIDE_TRACKING_WINDOW":
        if view.session_status == "COMPLETED":
            return "SESSION_COMPLETED", MESSAGES["SESSION_COMPLETED"]
        if view.attendance_status == "NO_SHIFT":
            msg = MESSAGES["UNSCHEDULED"] + (" Unscheduled attendance is not allowed by your organization, so no work session is created."
                                             if not settings.allow_unscheduled_attendance else "")
            return "UNSCHEDULED", msg
        return "OUTSIDE_WORKING_WINDOW", MESSAGES["OUTSIDE_WORKING_WINDOW"]
    if "AUTO_CHECKIN" in effects:
        return "AUTO_CHECKIN", MESSAGES["AUTO_CHECKIN"]
    if "RETURN_TO_OFFICE" in effects:
        return "SESSION_RESUMED", MESSAGES["SESSION_RESUMED"]
    if "FINAL_CHECKOUT" in effects:
        return "SESSION_COMPLETED", MESSAGES["SESSION_COMPLETED"]
    if view.zone_status == "NO_OFFICE":
        return "NO_OFFICE", MESSAGES["NO_OFFICE"]
    if view.session_status == "TEMPORARY_EXIT":
        return "TEMPORARY_EXIT", MESSAGES["TEMPORARY_EXIT"]
    inaccurate = reading.get("result") == "LOW_ACCURACY" or (reading.get("zone") == "UNCERTAIN" and reading.get("result") != "REJECTED")
    if view.session_status == "ACTIVE":
        if view.is_unscheduled:
            return "UNSCHEDULED", "Unscheduled attendance: your session is active without a scheduled shift."
        msg = MESSAGES["ACTIVE_SESSION"]
        conf = reading.get("confirmation") or {}
        if conf.get("target") == "OUTSIDE":
            msg = f"Session active. Leaving the office detected ({conf['readings']}/{conf['required']} readings to confirm a temporary exit)."
        elif inaccurate:
            msg += " (Last GPS reading was not precise enough; still using your validated position.)"
        return "ACTIVE_SESSION", msg
    if inaccurate:
        return "GPS_INACCURATE", MESSAGES["GPS_INACCURATE"]
    if view.zone_status == "INSIDE":
        if view.session_status == "COMPLETED":
            return "SESSION_COMPLETED", MESSAGES["SESSION_COMPLETED"] + " You are still inside the office zone."
        if not settings.automatic_attendance:
            return "INSIDE_GEOFENCE", MESSAGES["INSIDE_GEOFENCE"] + (" Use Check in to start your work day." if settings.manual_actions_allowed else "")
        if not settings.automatic_checkin_enabled:
            return "INSIDE_GEOFENCE", MESSAGES["INSIDE_GEOFENCE"] + " Automatic check-in is disabled; use Check in."
        conf = reading.get("confirmation") or {}
        if conf.get("target") == "INSIDE":
            return "INSIDE_GEOFENCE", f"Arrival detected — confirming ({conf['readings']}/{conf['required']} readings)…"
        return "INSIDE_GEOFENCE", MESSAGES["INSIDE_GEOFENCE"]
    if view.session_status == "COMPLETED":
        return "SESSION_COMPLETED", MESSAGES["SESSION_COMPLETED"]
    if view.zone_status in ("OUTSIDE", "LOCATION_DETECTED", "STALE", "UNKNOWN", "LOCATION_DENIED"):
        state = {"OUTSIDE": "OUTSIDE_GEOFENCE"}.get(view.zone_status, view.zone_status)
        return state, MESSAGES[state]
    return "UNKNOWN", MESSAGES["UNKNOWN"]
