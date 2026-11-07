"""Admin amallari (panel va bot uchun umumiy): chiqarish, vaqtga qoʻyish, rad etish."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.pipeline.slots import next_free_slot
from app.pipeline.state import PostStatus, transition
from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

S = PostStatus
ALLOWED: dict[str, frozenset[PostStatus]] = {
    "publish": frozenset({S.PENDING_APPROVAL, S.SCHEDULED, S.FAILED}),
    "schedule": frozenset({S.PENDING_APPROVAL, S.FAILED}),
    "reject": frozenset({S.PENDING_APPROVAL, S.SCHEDULED, S.FAILED}),
}


async def admin_action(ctx: AppContext, post_id: int, action: str, actor: str = "admin") -> tuple[bool, str]:
    post = await ctx.repo.posts.get(post_id)
    if post is None:
        return False, "Post topilmadi"
    if action not in ALLOWED:
        return False, "Nomaʼlum amal"
    status = PostStatus(post.status)
    if status not in ALLOWED[action]:
        return False, f"Bu postning holati: {status.value} — amal bajarilmaydi"
    if action == "reject":
        await transition(ctx.repo, post, S.REJECTED, actor)
        await ctx.repo.posts.save(post)
        return True, "❌ Rad etildi"
    if action == "publish":
        post.scheduled_at = utcnow()
        if status != S.SCHEDULED:
            await transition(ctx.repo, post, S.SCHEDULED, actor, action="publish")
        await ctx.repo.posts.save(post)
        ok = await ctx.service("publisher").publish(post_id)
        return ok, "✅ Kanalga chiqarildi" if ok else "❌ Chiqmadi — «Xatolar» boʻlimini koʻring"
    # schedule: kelajakdagi vaqti saqlanadi, aks holda keyingi boʻsh slot
    if post.scheduled_at is None or post.scheduled_at <= utcnow():
        post.scheduled_at, slot = await next_free_slot(ctx)
        if slot:
            post.slot = slot
    await transition(ctx.repo, post, S.SCHEDULED, actor, action="schedule")
    await ctx.repo.posts.save(post)
    return True, f"🕒 {to_tz(post.scheduled_at, ctx.settings.tz):%d.%m %H:%M} ga qoʻyildi"
