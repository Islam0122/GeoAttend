"""Time helpers. All persisted instants are timezone-aware UTC."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc

# Tests may freeze the clock by setting this.
_now_override: datetime | None = None


def utcnow() -> datetime:
    if _now_override is not None:
        return _now_override
    return datetime.now(UTC)


def set_now(value: datetime | None) -> None:
    global _now_override
    _now_override = ensure_utc(value) if value else None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:  # pragma: no cover - validated earlier
        raise ValueError(f"Unknown timezone: {name}") from exc


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def local_date(instant: datetime, tz: str) -> date:
    return ensure_utc(instant).astimezone(get_zone(tz)).date()


def local_to_utc(day: date, at: time, tz: str) -> datetime:
    """Interpret wall-clock `day at` in `tz` (DST-aware) and return UTC."""
    return datetime.combine(day, at, tzinfo=get_zone(tz)).astimezone(UTC)


def minutes_between(start: datetime, end: datetime) -> int:
    """Whole minutes from start to end (floored, never negative)."""
    seconds = (ensure_utc(end) - ensure_utc(start)).total_seconds()
    return max(0, int(seconds // 60))


def day_bounds_utc(day: date, tz: str) -> tuple[datetime, datetime]:
    start = local_to_utc(day, time(0, 0), tz)
    end = local_to_utc(day + timedelta(days=1), time(0, 0), tz)
    return start, end
