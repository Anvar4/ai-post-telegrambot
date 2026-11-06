"""Vaqt yordamchilari: Toshkent vaqti, jim soatlar, kun chegaralari."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
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


def parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")
    return time(int(hh), int(mm))


_WHEN_RE = re.compile(
    r"^(?:(?P<d>\d{1,2})\.(?P<m>\d{1,2})(?:\.(?P<y>\d{4}))?\s+)?(?P<hh>\d{1,2}):(?P<mm>\d{2})$"
)


def parse_when(text: str, now: datetime) -> datetime | None:
    """Admin yozgan vaqt: `HH:MM` (bugun, oʻtgan boʻlsa ertaga), `DD.MM HH:MM`, `DD.MM.YYYY HH:MM`.

    `now` — mahalliy (aware) vaqt; natija shu zonada. Notoʻgʻri yoki oʻtgan sana — None.
    """
    m = _WHEN_RE.match(text.strip())
    if m is None:
        return None
    try:
        at = time(int(m["hh"]), int(m["mm"]))
        if m["d"] is None:
            result = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
            return result if result > now else result + timedelta(days=1)
        year = int(m["y"]) if m["y"] else now.year
        result = datetime.combine(date(year, int(m["m"]), int(m["d"])), at, tzinfo=now.tzinfo)
        if result <= now and not m["y"]:
            result = result.replace(year=year + 1)
    except ValueError:
        return None
    return result if result > now else None


def in_quiet_hours(
    dt: datetime, start: time = time(23, 0), end: time = time(7, 0), name: str = DEFAULT_TZ
) -> bool:
    t = to_tz(dt, name).time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def shift_out_of_quiet(
    dt: datetime,
    start: time = time(23, 0),
    end: time = time(7, 0),
    resume: time = time(7, 30),
    name: str = DEFAULT_TZ,
) -> datetime:
    """Jim soatlarga tushgan vaqtni keyingi `resume` vaqtiga suradi (Toshkent vaqtida qaytaradi)."""
    if not in_quiet_hours(dt, start, end, name):
        return dt
    local = to_tz(dt, name)
    day = local.date() if local.time() < end else local.date() + timedelta(days=1)
    return datetime.combine(day, resume, tzinfo=ZoneInfo(name))
