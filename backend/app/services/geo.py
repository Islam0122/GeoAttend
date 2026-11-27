"""Pure geodesy + geofence classification. No I/O, fully unit-testable."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.models.enums import GeofencePresence, Zone

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean Earth radius


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def validate_coordinates(lat: float, lon: float) -> str | None:
    """Return a rejection reason or None when the coordinates are plausible."""
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return "INVALID_COORDINATES"
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return "COORDINATES_OUT_OF_RANGE"
    if abs(lat) < 1e-7 and abs(lon) < 1e-7:
        return "NULL_ISLAND"  # (0,0) is the classic "no fix" value
    return None


def validate_accuracy(accuracy_m: float, max_reasonable_m: float) -> str | None:
    if accuracy_m is None or not math.isfinite(accuracy_m) or accuracy_m <= 0:
        return "INVALID_ACCURACY"
    if accuracy_m > max_reasonable_m:
        return "ACCURACY_UNREASONABLE"
    return None


@dataclass(frozen=True)
class FenceParams:
    radius_m: float
    max_accuracy_m: float
    entry_buffer_m: float = 0.0
    exit_buffer_m: float = 0.0


def classify(distance_m: float, accuracy_m: float, fence: FenceParams) -> Zone:
    """
    Confirmed inside : distance + accuracy <= radius - entry_buffer
    Confirmed outside: distance - accuracy >  radius + exit_buffer
    Otherwise (or accuracy worse than the fence allows): UNCERTAIN.
    With zero buffers this is exactly the base rule.
    """
    if accuracy_m > fence.max_accuracy_m:
        return Zone.UNCERTAIN
    if distance_m + accuracy_m <= fence.radius_m - fence.entry_buffer_m:
        return Zone.INSIDE
    if distance_m - accuracy_m > fence.radius_m + fence.exit_buffer_m:
        return Zone.OUTSIDE
    return Zone.UNCERTAIN


def implied_speed_mps(lat1: float, lon1: float, t1: datetime, lat2: float, lon2: float, t2: datetime) -> tuple[float, float]:
    """(distance_m, speed_mps) between two fixes."""
    d = haversine_m(lat1, lon1, lat2, lon2)
    dt = abs((t2 - t1).total_seconds())
    return d, (d / dt if dt > 0 else math.inf if d > 0 else 0.0)


def is_suspicious_jump(distance_m: float, speed_mps: float, acc1: float, acc2: float, max_speed_mps: float) -> bool:
    """A jump is suspicious only if it cannot be explained by the reported accuracy of both fixes."""
    if distance_m <= acc1 + acc2:
        return False
    return speed_mps > max_speed_mps


# ---------------------------------------------------------------- hysteresis ----

@dataclass
class StabilityConfig:
    required_consecutive: int
    stability_window_seconds: int
    # Automatic attendance policy: separate confirmation counts (defaults 2 to enter, 3 to exit).
    entry_required: int | None = None
    exit_required: int | None = None

    def required_for(self, target: GeofencePresence) -> int:
        if target == GeofencePresence.INSIDE and self.entry_required:
            return self.entry_required
        if target == GeofencePresence.OUTSIDE and self.exit_required:
            return self.exit_required
        return self.required_consecutive


@dataclass
class PresenceState:
    presence: GeofencePresence
    candidate: GeofencePresence | None
    candidate_count: int
    candidate_since: datetime | None


@dataclass(frozen=True)
class StepResult:
    state: PresenceState
    confirmed: GeofencePresence | None  # set when a transition was confirmed by this reading
    occurred_at: datetime | None        # first reading of the confirming streak


def step(state: PresenceState, zone: Zone, at: datetime, cfg: StabilityConfig) -> StepResult:
    """
    Advance the presence state machine with one reading.
    - UNCERTAIN readings neither count nor reset a streak.
    - A reading equal to the current presence cancels any opposite candidate (flapping protection).
    - A transition is confirmed after N consecutive agreeing readings spanning >= the stability window.
    """
    if zone == Zone.UNCERTAIN:
        return StepResult(state, None, None)
    reading = GeofencePresence.INSIDE if zone == Zone.INSIDE else GeofencePresence.OUTSIDE
    if reading == state.presence:
        return StepResult(PresenceState(state.presence, None, 0, None), None, None)

    if state.candidate == reading and state.candidate_since is not None:
        count, since = state.candidate_count + 1, state.candidate_since
    else:
        count, since = 1, at

    elapsed = (at - since).total_seconds()
    if count >= cfg.required_for(reading) and elapsed >= cfg.stability_window_seconds:
        return StepResult(PresenceState(reading, None, 0, None), reading, since)
    return StepResult(PresenceState(state.presence, reading, count, since), None, None)
