"""Tasdiqlash oynasi: rasm + post matni + muharrir bahosi + tugmalar (adminga)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup
from loguru import logger

from app.bot.keyboards import approval_keyboard, manual_keyboard
from app.content.formatting import escape, visible_length
from app.content.limits import CAPTION_LIMIT, MESSAGE_LIMIT
from app.db.models import Post
from app.pipeline.compose import compose
from app.pipeline.slots import free_slots
from app.pipeline.state import PostKind
from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

KIND_UZ = {
    "news": "yangilik",
    "alert": "kiber ogohlantirish",
    "tool": "ilova",
    "site": "sayt",
    "tip": "maslahat",
    "poll": "soʻrovnoma",
    "quiz": "test",
    "digest": "dayjest",
    "qa": "savol-javob",
    "manual": "qoʻlda post",
}
MEDIA_UZ = {"photo": "rasm", "video": "video", "animation": "GIF"}


def _load(path: str | None) -> bytes | None:
    if not path:
        return None
    p = Path(path)
    return p.read_bytes() if p.is_file() else None


def poll_preview(post: Post) -> str:
    poll = (post.extra or {}).get("poll") or {}
    lines = [f"📊 <b>{escape(poll.get('question', ''))}</b>"]
    correct = poll.get("correct_option_id")
    for i, opt in enumerate(poll.get("options", [])):
        mark = "✅" if poll.get("quiz") and i == correct else "▫️"
        lines.append(f"{mark} {escape(opt)}")
    if poll.get("explanation"):
        lines.append(f"\n💡 {escape(poll['explanation'])}")
    return "\n".join(lines)


def info_text(post: Post, tz: str) -> str:
    report = post.check_report or {}
    when = to_tz(post.scheduled_at, tz).strftime("%d.%m %H:%M") if post.scheduled_at else "darhol"
    lines = [
        f"📝 <b>Qoralama #{post.id}</b> · {KIND_UZ.get(post.kind, post.kind)} · ⏰ {when}",
        f"Ball: {post.score if post.score is not None else '—'} · "
        f"Tekshiruv: <b>{report.get('verdict', '—')}</b>"
        + (" (zaxira model)" if report.get("degraded") else ""),
    ]
    extra = post.extra or {}
    if extra.get("why_uz"):
        lines.append(f"💡 {escape(str(extra['why_uz']))}")
    if extra.get("risk_flags"):
        lines.append("⚠️ Xavf belgilari: " + escape(", ".join(map(str, extra["risk_flags"]))))
    if post.approval_reason:
        lines.append(f"❗️ {escape(post.approval_reason)}")
    issues = [*report.get("code_issues", []), *report.get("issues", [])]
    for issue in issues[:4]:
        lines.append(
            f"• [{escape(str(issue.get('type')))}] "
            f"{escape(str(issue.get('fix') or issue.get('quote')))[:200]}"
        )
    for note in report.get("link_notes", [])[:2]:
        lines.append(f"• {escape(note)}")
    for url in (post.source_urls or [])[:3]:
        lines.append(f"🔗 {escape(url)}")
    return "\n".join(lines)[:MESSAGE_LIMIT]


async def manual_prompt(ctx: AppContext, post: Post) -> tuple[str, InlineKeyboardMarkup]:
    """Qoʻlda post uchun "qachon chiqarilsin?" matni va tugmalari (keyingi 3 ta boʻsh slot)."""
    media = (post.extra or {}).get("media")
    what = MEDIA_UZ.get(media["type"], media["type"]) if media else "matn"
    when = (
        to_tz(post.scheduled_at, ctx.settings.tz).strftime("%d.%m %H:%M")
        if post.scheduled_at and post.status == "SCHEDULED"
        else "vaqt tanlanmagan"
    )
    text = f"🗂 <b>Qoʻlda post #{post.id}</b> · {what} · ⏰ {when}\nQachon chiqarilsin?"
    slots = [t for t, _ in await free_slots(ctx)]
    return text, manual_keyboard(post.id, slots, ctx.settings.tz)  # type: ignore[arg-type]


async def _send_manual(ctx: AppContext, post: Post) -> None:
    """Qoʻlda post: kanalda qanday chiqsa, xuddi shunday koʻrinish + vaqt tugmalari."""
    info, kb = await manual_prompt(ctx, post)
    for admin_id in ctx.settings.admin_ids:
        try:
            for msg in compose(post, None):
                if msg.kind == "media" and msg.media:
                    await ctx.sender.send_media(admin_id, msg.media["type"], msg.media["file_id"], msg.text)
                else:
                    await ctx.sender.send_message(admin_id, msg.text or "")
            await ctx.sender.send_message(admin_id, info, reply_markup=kb)
        except Exception as exc:
            logger.warning("Qoʻlda post koʻrinishi yuborilmadi ({}): {}", admin_id, exc)


async def send_for_approval(ctx: AppContext, post_id: int) -> None:
    post = await ctx.repo.posts.get(post_id)
    if post is None:
        return
    if post.kind == PostKind.MANUAL:
        await _send_manual(ctx, post)
        return
    post.approval_sent_at = utcnow()
    await ctx.repo.posts.update(post_id, {"approval_sent_at": post.approval_sent_at})
    image = _load(post.image_path)
    is_poll = post.kind in (PostKind.POLL, PostKind.QUIZ)
    body = poll_preview(post) if is_poll else post.text_html
    info = info_text(post, ctx.settings.tz)
    for admin_id in ctx.settings.admin_ids:
        try:
            if image and not is_poll and visible_length(body) <= CAPTION_LIMIT:
                await ctx.sender.send_photo(admin_id, image, body)
            else:
                if image and not is_poll:
                    await ctx.sender.send_photo(admin_id, image, None)
                await ctx.sender.send_message(admin_id, body)
            await ctx.sender.send_message(admin_id, info, reply_markup=approval_keyboard(post_id))
        except Exception as exc:
            logger.warning("Tasdiqlash xabari yuborilmadi ({}): {}", admin_id, exc)
