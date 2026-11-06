"""Tasdiqlash tugmalari va tahrirlash oqimi (semi_auto)."""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import ApprovalCB
from app.bot.middlewares import AdminFilter
from app.context import AppContext
from app.pipeline.slots import next_free_slot
from app.pipeline.state import PostStatus, transition
from app.utils.timeutil import to_tz, utcnow

S = PostStatus
ALLOWED_FROM: dict[str, frozenset[PostStatus]] = {
    "pub": frozenset({S.PENDING_APPROVAL, S.SCHEDULED, S.FAILED}),
    "sched": frozenset({S.PENDING_APPROVAL, S.FAILED}),
    "edit": frozenset({S.PENDING_APPROVAL, S.SCHEDULED}),
    "rewrite": frozenset({S.PENDING_APPROVAL, S.SCHEDULED}),
    "img": frozenset({S.PENDING_APPROVAL, S.SCHEDULED}),
    "rej": frozenset({S.PENDING_APPROVAL, S.SCHEDULED, S.FAILED}),
    "aiimg": frozenset({S.PENDING_APPROVAL}),
    "noimg": frozenset({S.PENDING_APPROVAL}),
}


class EditState(StatesGroup):
    waiting = State()


def is_ready_text(text: str) -> bool:
    """Admin tayyor matn yubordimi yoki qisqa ko'rsatmami."""
    return len(text) >= 300 or "<b>" in text or text.count("\n") >= 3


async def on_approval(
    call: CallbackQuery, callback_data: ApprovalCB, ctx: AppContext, state: FSMContext
) -> None:
    pid, action = callback_data.post_id, callback_data.action
    post = await ctx.repo.get_post(pid)
    if post is None:
        await call.answer("Post topilmadi", show_alert=True)
        return
    if action not in ALLOWED_FROM or PostStatus(post.status) not in ALLOWED_FROM[action]:
        await call.answer(f"Bu postning holati: {post.status} — amal bajarilmaydi", show_alert=True)
        return

    if action in ("pub", "sched"):
        when, new_slot = utcnow(), None
        if action == "sched":
            if post.scheduled_at and post.scheduled_at > utcnow():
                when = post.scheduled_at
            else:
                when, new_slot = await next_free_slot(ctx)
        p = await ctx.repo.posts.get(pid)
        assert p is not None
        p.scheduled_at = when
        if new_slot:
            p.slot = new_slot  # AI shu slotga yana post tayyorlamaydi
        if p.status != S.SCHEDULED:
            await transition(ctx.repo, p, S.SCHEDULED, "admin", action=action)
        await ctx.repo.posts.save(p)
        if action == "pub":
            ok = await ctx.service("publisher").publish(pid)
            await call.answer("✅ Chiqarildi" if ok else "❌ Chiqmadi — /logs ni koʻring", show_alert=not ok)
        else:
            local = to_tz(when, ctx.settings.tz)  # type: ignore[arg-type]
            await call.answer(f"🕒 {local:%d.%m %H:%M} ga qoʻyildi")
        await _drop_keyboard(call)
    elif action == "rej":
        p = await ctx.repo.posts.get(pid)
        assert p is not None
        await transition(ctx.repo, p, S.REJECTED, "admin")
        await ctx.repo.posts.save(p)
        await call.answer("❌ Rad etildi")
        await _drop_keyboard(call)
    elif action == "edit":
        await state.set_state(EditState.waiting)
        await state.update_data(post_id=pid)
        await call.answer()
        if call.message is not None:
            await call.message.answer(
                f"✏️ Post #{pid}: yangi tayyor matnni yuboring yoki koʻrsatma yozing "
                "(masalan: «qisqaroq qil», «rasmiyroq»). Bekor qilish: /cancel"
            )
    elif action == "rewrite":
        await call.answer("🔄 Qayta yozilmoqda…")
        await ctx.service("pipeline").rewrite(pid)
    elif action == "img":
        await call.answer("🖼 Yangi rasm tayyorlanmoqda…")
        await ctx.service("pipeline").regenerate_image(pid)
    elif action == "aiimg":
        await call.answer("🎨 AI rasm tayyorlanmoqda…")
        await _drop_keyboard(call)
        result = await ctx.service("pipeline").use_ai_image(pid)
        if call.message is not None:
            await call.message.answer(result)
    elif action == "noimg":
        result = await ctx.service("pipeline").publish_without_image(pid)
        await call.answer(result)
        await _drop_keyboard(call)


async def _drop_keyboard(call: CallbackQuery) -> None:
    if call.message is not None and isinstance(call.message, Message):
        with contextlib.suppress(Exception):
            await call.message.edit_reply_markup(reply_markup=None)


async def on_edit_text(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    pid = int(data.get("post_id", 0))
    text = message.html_text if message.entities else (message.text or "")
    pipeline = ctx.service("pipeline")
    try:
        if is_ready_text(text):
            await pipeline.replace_text(pid, text)
        else:
            await message.answer("🔄 Koʻrsatma boʻyicha qayta yozilmoqda…")
            await pipeline.rewrite(pid, text)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.")


def create_router() -> Router:
    router = Router(name="approval")
    router.message.filter(AdminFilter(), F.chat.type == "private")
    router.callback_query.filter(AdminFilter())
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(on_edit_text, EditState.waiting, F.text)
    router.callback_query.register(on_approval, ApprovalCB.filter())
    return router
