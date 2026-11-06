"""Qoʻlda post: admin rasm, video, GIF yoki /new dan keyin matn yuboradi → vaqt tanlaydi → bot chiqaradi."""

from __future__ import annotations

import contextlib
from collections import deque
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.approval_view import MEDIA_UZ, manual_prompt
from app.bot.keyboards import ManualCB
from app.bot.middlewares import AdminFilter
from app.content.formatting import html_to_text
from app.content.limits import TITLE_SHORT_LIMIT
from app.context import AppContext
from app.db.models import Post
from app.pipeline.slots import free_slots
from app.pipeline.state import PostKind, PostStatus, transition
from app.utils.timeutil import parse_when, to_tz, utcnow

S = PostStatus
EDITABLE = frozenset({S.PENDING_APPROVAL, S.SCHEDULED})
TIME_HINT = (
    "Vaqtni yozing: <code>HH:MM</code> (bugun, oʻtgan boʻlsa ertaga), "
    "<code>DD.MM HH:MM</code> yoki <code>DD.MM.YYYY HH:MM</code>. Bekor qilish: /cancel"
)
_seen_albums: deque[str] = deque(maxlen=50)


class ManualState(StatesGroup):
    waiting_post = State()
    waiting_time = State()


def extract_media(message: Message) -> dict[str, str] | None:
    if message.photo:
        return {"type": "photo", "file_id": message.photo[-1].file_id}  # eng katta oʻlcham
    if message.video:
        return {"type": "video", "file_id": message.video.file_id}
    if message.animation:
        return {"type": "animation", "file_id": message.animation.file_id}
    return None


def _title(html: str, media: dict[str, str] | None) -> str:
    first = html_to_text(html).strip().split("\n", 1)[0].strip()
    if first:
        return first[:TITLE_SHORT_LIMIT]
    return f"({MEDIA_UZ.get(media['type'], 'media')})" if media else "(matn)"


async def create_manual_post(ctx: AppContext, html: str, media: dict[str, str] | None) -> Post:
    post = Post(
        kind=PostKind.MANUAL,
        status=S.PENDING_APPROVAL,
        text_html=html,
        title_short=_title(html, media),
        created_by="admin",
        approval_sent_at=utcnow(),
        extra={"media": media} if media else {},
    )
    await ctx.repo.posts.insert(post)
    await ctx.repo.audit("admin", "manual.create", post_id=post.id, media=media["type"] if media else None)
    return post


async def _reply_with_prompt(message: Message, ctx: AppContext, post: Post) -> None:
    text, kb = await manual_prompt(ctx, post)
    await message.reply(text, reply_markup=kb)


# ---------------------------------------------------------------- qabul qilish


async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.set_state(ManualState.waiting_post)
    await message.answer(
        "🗂 Yangi post: matnni yoki rasm / video / GIF ni (izoh bilan) yuboring — "
        "keyin qachon chiqarishni tanlaysiz. Bekor qilish: /cancel"
    )


async def on_media(message: Message, ctx: AppContext, state: FSMContext) -> None:
    if message.media_group_id:
        if message.media_group_id not in _seen_albums:
            _seen_albums.append(message.media_group_id)
            await message.answer(
                "⚠️ Albom (bir nechta fayl) hozircha qoʻllab-quvvatlanmaydi — "
                "bitta rasm, video yoki GIF yuboring."
            )
        return
    media = extract_media(message)
    if media is None:
        return
    await state.clear()
    post = await create_manual_post(ctx, message.html_text if message.caption else "", media)
    await _reply_with_prompt(message, ctx, post)


async def on_post_text(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    post = await create_manual_post(ctx, message.html_text, None)
    await _reply_with_prompt(message, ctx, post)


# ---------------------------------------------------------------- vaqt


async def _schedule(ctx: AppContext, post_id: int, when: datetime, slot: str | None) -> str | None:
    """Postni `when` ga qoʻyadi; xato boʻlsa sababini qaytaradi."""
    post = await ctx.repo.posts.get(post_id)
    if post is None:
        return "Post topilmadi"
    if PostStatus(post.status) not in EDITABLE:
        return f"Bu postning holati: {post.status} — vaqtini oʻzgartirib boʻlmaydi"
    post.scheduled_at = when
    post.slot = slot
    if post.status != S.SCHEDULED:
        await transition(ctx.repo, post, S.SCHEDULED, "admin", manual=True)
    await ctx.repo.posts.save(post)
    await ctx.repo.audit("admin", "manual.schedule", post_id=post_id, at=when.isoformat(), slot=slot)
    return None


async def _done(call: CallbackQuery, text: str) -> None:
    """Tugmali xabarni yakuniy holat matni bilan almashtiradi."""
    if call.message is not None and isinstance(call.message, Message):
        with contextlib.suppress(Exception):
            await call.message.edit_text(text, reply_markup=None)


async def on_manual(call: CallbackQuery, callback_data: ManualCB, ctx: AppContext, state: FSMContext) -> None:
    pid, action = callback_data.post_id, callback_data.action
    post = await ctx.repo.posts.get(pid)
    if post is None or post.kind != PostKind.MANUAL:
        await call.answer("Post topilmadi", show_alert=True)
        return
    if PostStatus(post.status) not in EDITABLE:
        await call.answer(f"Bu postning holati: {post.status} — amal bajarilmaydi", show_alert=True)
        return
    tz = ctx.settings.tz
    if action == "now":
        if error := await _schedule(ctx, pid, utcnow(), None):
            await call.answer(error, show_alert=True)
            return
        ok = await ctx.service("publisher").publish(pid)
        await call.answer("✅ Chiqarildi" if ok else "❌ Chiqmadi — /logs ni koʻring", show_alert=not ok)
        if ok:
            await _done(call, f"✅ Qoʻlda post #{pid} chiqarildi.")
    elif action == "at":
        when = datetime.fromtimestamp(callback_data.ts, UTC)
        if when <= utcnow():
            await call.answer("Bu vaqt oʻtib ketdi — boshqasini tanlang", show_alert=True)
            return
        slot = next((key for t, key in await free_slots(ctx, limit=10) if t == when), None)
        if error := await _schedule(ctx, pid, when, slot):
            await call.answer(error, show_alert=True)
            return
        label = f"{to_tz(when, tz):%d.%m %H:%M}"
        await call.answer(f"🕒 {label} ga qoʻyildi")
        await _done(call, f"🕒 Qoʻlda post #{pid} rejada: {label}. Navbat: /queue")
    elif action == "other":
        await state.set_state(ManualState.waiting_time)
        await state.update_data(post_id=pid)
        await call.answer()
        if call.message is not None:
            await call.message.answer(f"⏰ Post #{pid}. {TIME_HINT}")
    elif action == "cancel":
        await transition(ctx.repo, post, S.REJECTED, "admin", manual=True)
        await ctx.repo.posts.save(post)
        await call.answer("❌ Bekor qilindi")
        await _done(call, f"❌ Qoʻlda post #{pid} bekor qilindi.")


async def on_time_text(message: Message, ctx: AppContext, state: FSMContext) -> None:
    pid = int((await state.get_data()).get("post_id", 0))
    local = parse_when(message.text or "", to_tz(utcnow(), ctx.settings.tz))
    if local is None:
        await message.answer(f"⚠️ Vaqt tushunilmadi yoki oʻtib ketgan. {TIME_HINT}")
        return
    await state.clear()
    if error := await _schedule(ctx, pid, local, None):
        await message.answer(f"⚠️ {error}")
        return
    await message.answer(f"🕒 Qoʻlda post #{pid} rejada: {local:%d.%m.%Y %H:%M}. Navbat: /queue")


def create_router() -> Router:
    router = Router(name="manual")
    router.message.filter(AdminFilter(), F.chat.type == "private")
    router.callback_query.filter(AdminFilter())
    router.message.register(cmd_new, Command("new"))
    router.message.register(on_media, F.photo | F.video | F.animation)
    not_command = ~F.text.startswith("/")
    router.message.register(on_post_text, ManualState.waiting_post, F.text, not_command)
    router.message.register(on_time_text, ManualState.waiting_time, F.text, not_command)
    router.callback_query.register(on_manual, ManualCB.filter())
    return router
