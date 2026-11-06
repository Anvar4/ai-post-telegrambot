"""Boʻsh slotlar: qoʻlda post va tasdiqlashda taklif qilinadigan keyingi vaqtlar."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.content.schedule import upcoming_slot_times
from app.pipeline.state import PostStatus
from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

S = PostStatus
# Shu holatlardagi post slotni band qilmaydi
FREEING = [S.REJECTED.value, S.EXPIRED.value, S.FAILED.value]
LEAD = timedelta(minutes=5)


def slot_key(when: datetime, tz: str) -> str:
    """Slot kaliti: mahalliy sana va vaqt (`2026-11-06:13:00`) — bir slotga bitta post."""
    local = to_tz(when, tz)
    return f"{local.date().isoformat()}:{local:%H:%M}"


async def free_slots(
    ctx: AppContext, limit: int = 3, now: datetime | None = None
) -> list[tuple[datetime, str]]:
    """Keyingi boʻsh slotlar: (vaqt, slot kaliti). Band — shu kalitli yoki aynan shu vaqtga qoʻyilgan post."""
    now = now or utcnow()
    tz = ctx.settings.tz
    upcoming = upcoming_slot_times(now + LEAD, await ctx.runtime.get("slot_times"), tz)
    keys = [slot_key(t, tz) for t in upcoming]
    busy_keys = {
        p.slot for p in await ctx.repo.posts.find({"slot": {"$in": keys}, "status": {"$nin": FREEING}})
    }
    busy_times = {
        p.scheduled_at.replace(second=0, microsecond=0)
        for p in await ctx.repo.posts.find({"status": S.SCHEDULED, "scheduled_at": {"$gte": now}})
        if p.scheduled_at is not None
    }
    out: list[tuple[datetime, str]] = []
    for when, key in zip(upcoming, keys, strict=True):
        if key in busy_keys or when.replace(second=0, microsecond=0) in busy_times:
            continue
        out.append((when, key))
        if len(out) >= limit:
            break
    return out
