"""Izohlar guruhi: moderatsiya, @mention/reply orqali savol-javob, izohlar hisobi, ban tugmasi."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.bot.keyboards import ModCB
from app.bot.middlewares import AdminFilter
from app.context import AppContext

LINK_ENTITY_TYPES = frozenset({"url", "text_link", "mention"})


class ManagedGroupFilter(Filter):
    """Faqat sozlangan izohlar guruhi va test guruhi."""

    async def __call__(self, message: Message, ctx: AppContext) -> bool:
        managed = {ctx.settings.discussion_group_id, ctx.settings.test_group_id} - {None}
        return message.chat.type in ("group", "supergroup") and message.chat.id in managed


async def _bot_username(ctx: AppContext, bot: Bot) -> str:
    name = ctx.services.get("bot_username")
    if not name:
        me = await bot.me()
        name = me.username or ""
        ctx.services["bot_username"] = name
    return str(name)


async def on_group_message(message: Message, ctx: AppContext, bot: Bot) -> None:
    moderation = ctx.services.get("moderation")
    metrics = ctx.services.get("metrics")
    if message.new_chat_members:
        if moderation is not None:
            for member in message.new_chat_members:
                moderation.mark_new_member(message.chat.id, member.id)
        return
    if message.is_automatic_forward:
        origin = getattr(message.forward_origin, "message_id", None)
        if metrics is not None and origin:
            await metrics.on_auto_forward(int(origin), message.message_id)
        return
    if message.sender_chat is not None and message.sender_chat.id == ctx.settings.channel_id:
        return
    user = message.from_user
    if user is None or user.is_bot:
        return
    text = message.text or message.caption or ""
    reply = message.reply_to_message
    if moderation is not None:
        has_link = any(
            e.type in LINK_ENTITY_TYPES for e in (message.entities or message.caption_entities or [])
        )
        first = moderation.pop_first_message(message.chat.id, user.id)
        result = await moderation.handle(
            message.chat.id,
            message.message_id,
            user.id,
            text,
            is_new_member_first_msg=first,
            has_link=has_link,
            user_name=user.first_name,
        )
        if result.action != "none":
            return

    if metrics is not None:
        root = (
            reply.message_id
            if reply is not None and reply.is_automatic_forward
            else message.message_thread_id
        )
        if root:
            await metrics.on_comment(root)

    qa = ctx.services.get("qa")
    if qa is None or not text:
        return
    username = await _bot_username(ctx, bot)
    mention = f"@{username}".lower() if username else ""
    mentioned = bool(mention) and mention in text.lower()
    replied_to_bot = reply is not None and reply.from_user is not None and reply.from_user.id == bot.id
    if not (mentioned or replied_to_bot):
        return
    question = text
    if mention:
        idx = question.lower().find(mention)
        if idx >= 0:
            question = (question[:idx] + question[idx + len(mention) :]).strip()
    if not question:
        return
    answer = await qa.answer(user.id, question, "comments")
    try:
        await message.reply(answer)
    except Exception as exc:
        logger.warning("Guruhda javob yuborilmadi: {}", exc)


async def on_mod_callback(call: CallbackQuery, callback_data: ModCB, ctx: AppContext) -> None:
    moderation = ctx.services.get("moderation")
    if callback_data.action == "ban" and moderation is not None:
        await moderation.ban(callback_data.chat_id, callback_data.user_id)
        await ctx.repo.audit("admin", "ban", chat_id=callback_data.chat_id)
        await call.answer("🚫 Ban qilindi")
    else:
        await call.answer("Bekor qilindi")
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            logger.debug("Klaviatura olib tashlanmadi: {}", exc)


def create_router() -> Router:
    router = Router(name="group")
    router.message.filter(ManagedGroupFilter())
    router.message.register(on_group_message)
    router.callback_query.register(on_mod_callback, ModCB.filter(), AdminFilter())
    return router
