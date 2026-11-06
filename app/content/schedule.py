"""Kunlik jadval: slot vaqtlari, kun rejasi (`plan_day`) va turkumlar (SPEC 5-bo'lim + /settings)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.pipeline.state import PostKind
from app.utils.timeutil import DEFAULT_TZ, parse_hhmm

DEFAULT_SLOT_TIMES = ("08:30", "13:00", "19:30")
MAX_SLOTS_PER_DAY = 8
# /settings dagi tanlov katakchalari (jim soatlar 23:00–07:00 dan tashqarida)
TIME_CHOICES = (
    "07:00", "07:30", "08:00", "08:30", "09:00", "10:00", "11:00", "12:00",
    "12:30", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "18:30",
    "19:00", "19:30", "20:00", "20:30", "21:00", "21:30", "22:00",
)  # fmt: skip

CATEGORY_LABELS: dict[str, str] = {
    "kiber": "🛡 Kiberxavfsizlik",
    "yangilik": "📰 IT yangiliklar",
    "ai": "🤖 Sunʼiy intellekt",
    "ilova": "🧰 Foydali ilovalar",
    "sayt": "🌐 Foydali saytlar",
    "maslahat": "💡 Maslahatlar",
}
ALL_CATEGORIES = tuple(CATEGORY_LABELS)
NEWS_CATEGORIES = ("kiber", "yangilik", "ai")
FEATURE_CATEGORY: dict[PostKind, str] = {
    PostKind.TOOL: "ilova",
    PostKind.SITE: "sayt",
    PostKind.TIP: "maslahat",
}
FEATURE_CYCLE = (PostKind.TOOL, PostKind.SITE, PostKind.TIP)
# 0 = dushanba ... 6 = yakshanba: kunning birinchi "foydali" posti (ilova haftasiga 3, sayt 2, maslahat 2)
FEATURE_START: dict[int, PostKind] = {
    0: PostKind.TOOL,
    1: PostKind.SITE,
    2: PostKind.TIP,
    3: PostKind.TOOL,
    4: PostKind.SITE,
    5: PostKind.TOOL,
    6: PostKind.TIP,
}
POLL_OFFSET, QUIZ_OFFSET = 1, 2  # standart: so'rovnoma — seshanba/juma, test — chorshanba/shanba

# Post turi -> saralovchi kategoriyalari
KIND_CATEGORIES: dict[PostKind, tuple[str, ...]] = {
    PostKind.NEWS: ("kiber", "yangilik", "ai"),
    PostKind.ALERT: ("kiber",),
    PostKind.TOOL: ("ilova",),
    PostKind.SITE: ("sayt",),
}


def interactive_days(per_week: int, offset: int) -> set[int]:
    """Haftada `per_week` marta — kunlarga teng taqsimlangan (0..7)."""
    per_week = max(0, min(7, per_week))
    return {(offset + i * 7 // per_week) % 7 for i in range(per_week)}


def plan_day(
    weekday: int,
    times: Sequence[str],
    categories: Iterable[str],
    polls_per_week: int,
    quizzes_per_week: int,
) -> list[PostKind]:
    """Kun rejasi: har bir vaqt uchun post turi.

    Juft o'rinlar — yangilik, toq o'rinlar — ilova/sayt/maslahat (haftalik aylanish);
    so'rovnoma va test kunida ular oxirgi o'rinlarni egallaydi (birinchi o'rin — yangilik).
    O'chirilgan turkumlar o'rniga qolganlari ishlatiladi.
    """
    n = len(times)
    if n == 0:
        return []
    cats = set(categories)
    news_ok = any(c in cats for c in NEWS_CATEGORIES)
    start = FEATURE_CYCLE.index(FEATURE_START[weekday % 7])
    rotated = FEATURE_CYCLE[start:] + FEATURE_CYCLE[:start]
    features = [k for k in rotated if FEATURE_CATEGORY[k] in cats]
    plan: list[PostKind] = []
    used = 0
    for i in range(n):
        if (i % 2 == 0 and news_ok) or not features:
            plan.append(PostKind.NEWS)
        else:
            plan.append(features[used % len(features)])
            used += 1
    extras = [
        kind
        for kind, per_week, offset in (
            (PostKind.POLL, polls_per_week, POLL_OFFSET),
            (PostKind.QUIZ, quizzes_per_week, QUIZ_OFFSET),
        )
        if weekday % 7 in interactive_days(per_week, offset)
    ]
    positions = list(range(n - 1, 0, -1)) if n > 1 else [0]
    for kind, pos in zip(extras, positions, strict=False):
        plan[pos] = kind
    return plan


def normalize_times(values: Iterable[str]) -> list[str]:
    """HH:MM ro'yxati: tekshirilgan, takrorsiz, o'sish tartibida. Xato bo'lsa ValueError."""
    out: set[str] = set()
    for raw in values:
        v = raw.strip()
        if not v:
            continue
        t = parse_hhmm(v)  # ValueError — noto'g'ri vaqt
        out.add(f"{t:%H:%M}")
    return sorted(out)


def slot_datetime(day: date, hhmm: str, tz: str = DEFAULT_TZ) -> datetime:
    return datetime.combine(day, parse_hhmm(hhmm), tzinfo=ZoneInfo(tz))


def upcoming_slot_times(
    now: datetime, times: Sequence[str], tz: str = DEFAULT_TZ, days: int = 2
) -> list[datetime]:
    """`now` dan keyingi slot vaqtlari (Toshkent vaqtida, o'sish tartibida)."""
    local = now.astimezone(ZoneInfo(tz))
    out: list[datetime] = []
    for d in range(days + 1):
        day = local.date() + timedelta(days=d)
        for hhmm in times:
            dt = slot_datetime(day, hhmm, tz)
            if dt > local:
                out.append(dt)
    return sorted(out)
