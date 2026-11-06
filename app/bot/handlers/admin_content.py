"""Admin: /post, /queue, /show, /time, /sources, /source_add, /settings, /set, /digest."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy import select

from app.bot.approval_view import KIND_UZ, send_for_approval
from app.bot.handlers.admin import MENU_HANDLERS
from app.bot.keyboards import SourceCB
from app.bot.middlewares import AdminFilter
from app.content.formatting import escape
from app.context import AppContext
from app.db.models import Post, Source
from app.pipeline.state import PostStatus
from app.utils.runtime import RUNTIME_DEFAULTS
from app.utils.timeutil import parse_hhmm, to_tz, utcnow

S = PostStatus
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
STATUS_UZ = {S.PENDING_APPROVAL: "⏳ tasdiq kutmoqda", S.SCHEDULED: "🕒 rejada"}
CATEGORIES = ("kiber", "yangilik", "ai", "ilova", "sayt", "mahalliy")
INT_KEYS = {
    "approval_timeout_min": (5, 1440),
    "news_expiry_hours": (1, 72),
    "share_cta_every": (0, 50),
    "breaking_min_score": (50, 100),
    "min_score": (0, 100),
    "category_daily_cap": (1, 5),
    "prepare_minutes_before": (10, 180),
}
RESCHEDULE_KEYS = ("slots", "digest", "prepare_minutes_before")


# ---------------------------------------------------------------- /post


async def cmd_post(message: Message, command: CommandObject, ctx: AppContext) -> None:
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Foydalanish: /post &lt;mavzu yoki havola&gt;")
        return
    await message.answer("⏳ Post tayyorlanmoqda… qoralama shu yerga keladi.")
    try:
        pid = await ctx.service("pipeline").prepare_from_admin(arg)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    if pid is None:
        await message.answer("❌ Post tayyorlanmadi (tekshiruvdan oʻtmadi). /logs")


# ---------------------------------------------------------------- navbat


async def queue_text(ctx: AppContext) -> str:
    async with ctx.repo.session() as s:
        rows = (
            (
                await s.execute(
                    select(Post)
                    .where(Post.status.in_((S.PENDING_APPROVAL, S.SCHEDULED)))
                    .order_by(Post.scheduled_at.is_(None), Post.scheduled_at, Post.id)
                    .limit(25)
                )
            )
            .scalars()
            .all()
        )
    if not rows:
        return "🗂 Navbat boʻsh."
    lines = ["🗂 <b>Navbat</b>"]
    for p in rows:
        when = to_tz(p.scheduled_at, ctx.settings.tz).strftime("%d.%m %H:%M") if p.scheduled_at else "—"
        lines.append(
            f"#{p.id} · {STATUS_UZ.get(PostStatus(p.status), p.status)} · {KIND_UZ.get(p.kind, p.kind)} · "
            f"{when} — {escape((p.title_short or '')[:50])}"
        )
    lines.append("\nKoʻrish va tugmalar: /show ID · Vaqtni oʻzgartirish: /time ID HH:MM")
    return "\n".join(lines)


async def cmd_queue(message: Message, ctx: AppContext) -> None:
    await message.answer(await queue_text(ctx))


async def cmd_show(message: Message, command: CommandObject, ctx: AppContext) -> None:
    try:
        pid = int((command.args or "").strip().lstrip("#"))
    except ValueError:
        await message.answer("Foydalanish: /show ID")
        return
    if await ctx.repo.get_post(pid) is None:
        await message.answer("Post topilmadi.")
        return
    await send_for_approval(ctx, pid)


async def cmd_time(message: Message, command: CommandObject, ctx: AppContext) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2 or not HHMM_RE.match(parts[1]):
        await message.answer("Foydalanish: /time ID HH:MM")
        return
    pid = int(parts[0].lstrip("#")) if parts[0].lstrip("#").isdigit() else 0
    local_now = to_tz(utcnow(), ctx.settings.tz)
    target = datetime.combine(local_now.date(), parse_hhmm(parts[1]), tzinfo=local_now.tzinfo)
    if target <= local_now:
        target += timedelta(days=1)
    async with ctx.repo.session() as s:
        post = await s.get(Post, pid)
        if post is None or post.status not in (S.PENDING_APPROVAL, S.SCHEDULED):
            await message.answer("Post topilmadi yoki uning vaqtini oʻzgartirib boʻlmaydi.")
            return
        post.scheduled_at = target
        await s.commit()
    await ctx.repo.audit("admin", "reschedule", post_id=pid, at=target.isoformat())
    await message.answer(f"🕒 Post #{pid}: {target:%d.%m %H:%M}")


# ---------------------------------------------------------------- manbalar


async def sources_view(ctx: AppContext) -> tuple[str, InlineKeyboardMarkup]:
    async with ctx.repo.session() as s:
        sources = (await s.execute(select(Source).order_by(Source.category, Source.id))).scalars().all()
    lines = ["📡 <b>Manbalar</b> (tugma — yoqish/oʻchirish)"]
    buttons: list[InlineKeyboardButton] = []
    for src in sources:
        status = "✅" if src.enabled else ("⏸" if src.auto_disabled_at else "⛔")
        ok = to_tz(src.last_ok_at, ctx.settings.tz).strftime("%d.%m %H:%M") if src.last_ok_at else "—"
        err = f" · xato×{src.fail_count}" if src.fail_count else ""
        lines.append(
            f"{status} #{src.id} {escape(src.name)} [{src.category}, {src.type}, ishonch {src.trust}] "
            f"oxirgi: {ok}{err}"
        )
        buttons.append(
            InlineKeyboardButton(
                text=f"{status} {src.name[:20]}",
                callback_data=SourceCB(action="toggle", source_id=src.id).pack(),
            )
        )
    lines.append("\nQoʻshish: /source_add URL kategoriya [nomi]\nKategoriyalar: " + ", ".join(CATEGORIES))
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(inline_keyboard=rows)


async def sources_text(ctx: AppContext) -> str:
    return (await sources_view(ctx))[0]


async def cmd_sources(message: Message, ctx: AppContext) -> None:
    text, kb = await sources_view(ctx)
    await message.answer(text, reply_markup=kb)


async def on_source_toggle(call: CallbackQuery, callback_data: SourceCB, ctx: AppContext) -> None:
    async with ctx.repo.session() as s:
        src = await s.get(Source, callback_data.source_id)
        if src is None:
            await call.answer("Manba topilmadi", show_alert=True)
            return
        src.enabled = not src.enabled
        src.auto_disabled_at = None
        src.fail_count = 0
        name, enabled = src.name, src.enabled
        await s.commit()
    await ctx.repo.audit("admin", "source.toggle", source_id=callback_data.source_id, enabled=enabled)
    await call.answer(f"{name}: {'yoqildi' if enabled else 'oʻchirildi'}")


async def cmd_source_add(message: Message, command: CommandObject, ctx: AppContext) -> None:
    parts = (command.args or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[0].startswith("https://") or parts[1] not in CATEGORIES:
        await message.answer(
            "Foydalanish: /source_add https://sayt/feed kategoriya [nomi]\nKategoriyalar: "
            + ", ".join(CATEGORIES)
        )
        return
    url, category = parts[0], parts[1]
    name = parts[2] if len(parts) > 2 else url.split("/")[2]
    async with ctx.repo.session() as s:
        if await s.scalar(select(Source.id).where(Source.url == url)):
            await message.answer("Bu manba allaqachon bor.")
            return
        s.add(Source(name=name[:200], type="rss", url=url, category=category, trust=3, lang="en"))
        await s.commit()
    await ctx.repo.audit("admin", "source.add", url=url, category=category)
    await message.answer(f"✅ Manba qoʻshildi: {escape(name)} ({category}). Keyingi yigʻishda tekshiriladi.")


# ---------------------------------------------------------------- sozlamalar


async def settings_text(ctx: AppContext) -> str:
    values = await ctx.runtime.all()
    lines = ["⚙️ <b>Sozlamalar</b>"]
    for key, value in values.items():
        lines.append(f"• <code>{key}</code> = {escape(str(value))}")
    lines.append(
        "\nOʻzgartirish: <code>/set kalit qiymat</code>\n"
        "Masalan: /set slots.morning 08:30 · /set quiet.start 23:00 · "
        "/set approval_timeout_action publish · /set min_score 55 · /set image_review false"
    )
    return "\n".join(lines)


async def cmd_settings(message: Message, ctx: AppContext) -> None:
    await message.answer(await settings_text(ctx))


def _parse_bool(value: str) -> bool | None:
    v = value.strip().lower()
    if v in {"true", "1", "ha", "on", "yes"}:
        return True
    if v in {"false", "0", "yoq", "yoʻq", "yo'q", "off", "no"}:
        return False
    return None


async def apply_setting(ctx: AppContext, key: str, raw: str) -> str:
    """Sozlamani tekshirib saqlaydi; xato bo'lsa ValueError."""
    base, _, sub = key.partition(".")
    if base not in RUNTIME_DEFAULTS or base in {"publish_mode", "paused"}:
        raise ValueError(f"Nomaʼlum kalit: {key} (rejim uchun /mode, toʻxtatish uchun /pause)")
    current: Any = await ctx.runtime.get(base)
    if isinstance(current, dict):
        if sub not in current:
            raise ValueError(f"{base} ichida mavjud kalitlar: {', '.join(current)}")
        if sub == "weekday":
            day = int(raw)
            if not 0 <= day <= 6:
                raise ValueError("weekday 0 (dushanba) … 6 (yakshanba)")
            current[sub] = day
        else:
            if not HHMM_RE.match(raw):
                raise ValueError("Vaqt HH:MM koʻrinishida boʻlsin")
            current[sub] = raw
        value: Any = current
    elif isinstance(current, bool):
        parsed = _parse_bool(raw)
        if parsed is None:
            raise ValueError("Qiymat true yoki false boʻlsin")
        value = parsed
    elif base in INT_KEYS:
        lo, hi = INT_KEYS[base]
        value = int(raw)
        if not lo <= value <= hi:
            raise ValueError(f"{base}: {lo}…{hi} oraligʻida")
    elif base == "approval_timeout_action":
        if raw not in {"wait", "publish"}:
            raise ValueError("wait yoki publish")
        value = raw
    else:
        raise ValueError(f"{key} ni oʻzgartirib boʻlmaydi")
    await ctx.runtime.set(base, value)
    if base in RESCHEDULE_KEYS and ctx.services.get("scheduler") is not None:
        from app.scheduler.setup import schedule_slots

        await schedule_slots(ctx, ctx.services["scheduler"])
    return f"✅ {key} = {escape(str(value))}"


async def cmd_set(message: Message, command: CommandObject, ctx: AppContext) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Foydalanish: /set kalit qiymat · Barcha kalitlar: /settings")
        return
    try:
        await message.answer(await apply_setting(ctx, parts[0], parts[1].strip()))
    except ValueError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")


# ---------------------------------------------------------------- dayjest


async def cmd_digest(message: Message, ctx: AppContext) -> None:
    await message.answer("⏳ Haftalik dayjest tayyorlanmoqda…")
    try:
        pid = await ctx.service("pipeline").prepare_digest(None)
    except Exception as exc:
        logger.exception("Dayjest xatosi")
        await message.answer(f"❌ Dayjest tayyorlanmadi: {escape(str(exc))[:300]}")
        return
    if pid is None:
        await message.answer("ℹ️ Dayjest tayyorlanmadi (postlar yetarli emas yoki tekshiruvdan oʻtmadi).")


# ---------------------------------------------------------------- so'rovnoma va test


async def _interactive(
    message: Message, command: CommandObject, ctx: AppContext, service: str, label: str
) -> None:
    topic = (command.args or "").strip() or None
    await message.answer(f"⏳ {label} tayyorlanmoqda… qoralama shu yerga keladi.")
    pid = await ctx.service(service).create(topic, created_by="admin")
    if pid is None:
        await message.answer(f"❌ {label} tayyorlanmadi (tekshiruvdan oʻtmadi).")


async def cmd_poll(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _interactive(message, command, ctx, "polls", "Soʻrovnoma")


async def cmd_quiz(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _interactive(message, command, ctx, "quizzes", "Test")


MENU_HANDLERS.update({"queue": queue_text, "sources": sources_text, "settings": settings_text})


def create_router() -> Router:
    router = Router(name="admin_content")
    router.message.filter(AdminFilter(), F.chat.type == "private")
    router.callback_query.filter(AdminFilter())
    router.message.register(cmd_post, Command("post"))
    router.message.register(cmd_queue, Command("queue"))
    router.message.register(cmd_show, Command("show"))
    router.message.register(cmd_time, Command("time"))
    router.message.register(cmd_sources, Command("sources"))
    router.message.register(cmd_source_add, Command("source_add"))
    router.message.register(cmd_settings, Command("settings"))
    router.message.register(cmd_set, Command("set"))
    router.message.register(cmd_digest, Command("digest"))
    router.message.register(cmd_poll, Command("poll"))
    router.message.register(cmd_quiz, Command("quiz"))
    router.callback_query.register(on_source_toggle, SourceCB.filter())
    return router
