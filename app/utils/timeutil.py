"""Vaqt yordamchilari: Toshkent vaqti, jim soatlar, kun chegaralari."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Tashkent"


def utcnow() -> datetime:
    return datetime.now(UTC)


def tzinfo(name: str = DEFAULT_TZ) -> ZoneInfo:
    return ZoneInfo(name)


def now_tz(name: str = DEFAULT_TZ) -> datetime:
    return datetime.now(ZoneInfo(name))


def to_tz(dt: datetime, name: str = DEFAULT_TZ) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ZoneInfo(name))


def day_bounds(dt: datetime, name: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Berilgan vaqtning mahalliy kuni boshi va oxiri (UTC, aware)."""
    local = to_tz(dt, name)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=ZoneInfo(name))
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)
