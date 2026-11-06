"""Kunlik jadval: slotlar va hafta kuniga qarab post turlari (SPEC 5-bo'lim)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.pipeline.state import PostKind
from app.utils.timeutil import DEFAULT_TZ, parse_hhmm

SLOT_NAMES = ("morning", "midday", "evening")

# 0 = dushanba ... 6 = yakshanba
# 13:00 — ilova haftasiga 3, sayt 2, maslahat 2
MIDDAY_ROTATION: dict[int, PostKind] = {
    0: PostKind.TOOL,
    1: PostKind.SITE,
    2: PostKind.TIP,
    3: PostKind.TOOL,
    4: PostKind.SITE,
    5: PostKind.TOOL,
    6: PostKind.TIP,
}
# 19:30 — so'rovnoma haftasiga 2, test 2, qolgani yangilik
EVENING_ROTATION: dict[int, PostKind] = {
    0: PostKind.NEWS,
    1: PostKind.POLL,
    2: PostKind.QUIZ,
    3: PostKind.NEWS,
    4: PostKind.POLL,
    5: PostKind.QUIZ,
    6: PostKind.NEWS,
}

# Post turi -> saralovchi kategoriyalari
KIND_CATEGORIES: dict[PostKind, tuple[str, ...]] = {
    PostKind.NEWS: ("kiber", "yangilik", "ai"),
    PostKind.ALERT: ("kiber",),
    PostKind.TOOL: ("ilova",),
    PostKind.SITE: ("sayt",),
}


def slot_kind(slot: str, weekday: int) -> PostKind:
    if slot == "midday":
        return MIDDAY_ROTATION[weekday]
    if slot == "evening":
        return EVENING_ROTATION[weekday]
    return PostKind.NEWS


def slot_datetime(day: date, hhmm: str, tz: str = DEFAULT_TZ) -> datetime:
    return datetime.combine(day, parse_hhmm(hhmm), tzinfo=ZoneInfo(tz))


def upcoming_slot_times(
    now: datetime, slots: dict[str, str], tz: str = DEFAULT_TZ, days: int = 2
) -> list[datetime]:
    """`now` dan keyingi slot vaqtlari (Toshkent vaqtida, o'sish tartibida)."""
    local = now.astimezone(ZoneInfo(tz))
    out: list[datetime] = []
    for d in range(days + 1):
        day = local.date() + timedelta(days=d)
        for name in SLOT_NAMES:
            if name in slots:
                dt = slot_datetime(day, slots[name], tz)
                if dt > local:
                    out.append(dt)
    return sorted(out)
