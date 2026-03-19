from __future__ import annotations

from datetime import datetime, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo

    def _load_timezone(name: str) -> tzinfo:
        return ZoneInfo(name)

except ImportError:
    import pytz

    def _load_timezone(name: str) -> tzinfo:
        return pytz.timezone(name)


NEW_YORK_TZ = _load_timezone("America/New_York")
SILVER_BULLET_WINDOWS_NY: tuple[tuple[int, int], ...] = ((3, 4), (10, 11), (14, 15))


def parse_candle_timestamp(candle: dict[str, object]) -> datetime | None:
    raw = candle.get("candle_date_time_utc") or candle.get("timestamp")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def is_in_silver_bullet_window(candle: dict[str, object]) -> bool:
    timestamp = parse_candle_timestamp(candle)
    if timestamp is None:
        return False
    local = timestamp.astimezone(NEW_YORK_TZ)
    return any(start <= local.hour < end for start, end in SILVER_BULLET_WINDOWS_NY)


__all__ = [
    "NEW_YORK_TZ",
    "SILVER_BULLET_WINDOWS_NY",
    "_load_timezone",
    "is_in_silver_bullet_window",
    "parse_candle_timestamp",
]
