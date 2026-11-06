"""Tasdiqlash oynasi: rasm + post matni + muharrir bahosi + tugmalar (adminga)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.bot.keyboards import approval_keyboard
from app.content.formatting import escape, visible_length
from app.content.limits import CAPTION_LIMIT, MESSAGE_LIMIT
from app.db.models import Post
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
}


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


async def send_for_approval(ctx: AppContext, post_id: int) -> None:
    async with ctx.repo.session() as s:
        post = await s.get(Post, post_id)
        if post is None:
            return
        post.approval_sent_at = utcnow()
        await s.commit()
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
