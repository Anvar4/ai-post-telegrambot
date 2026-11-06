"""Admin bo'lmaganlar uchun shaxsiy chat: savol-javob rejimi."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.middlewares import NotAdminFilter
from app.context import AppContext

WELCOME = (
    "Assalomu alaykum! Men <b>IT Dunyosi</b> kanalining yordamchisiman. "
    "IT, telefon, kompyuter, internet xavfsizligi, dasturlash va AI boʻyicha savolingizni yozing."
)


async def cmd_start(message: Message, ctx: AppContext) -> None:
    await message.answer(WELCOME)


async def other_command(message: Message, ctx: AppContext) -> None:
    await message.answer("Bu buyruq mavjud emas. Savolingizni oddiy matn bilan yozing.")


async def on_question(message: Message, ctx: AppContext) -> None:
    qa = ctx.services.get("qa")
    if qa is None or not message.from_user or not message.text:
        await message.answer("Savol-javob xizmati hozircha ishlamayapti. Keyinroq urinib koʻring.")
        return
    answer = await qa.answer(message.from_user.id, message.text, "dm")
    await message.answer(answer)


def create_router() -> Router:
    router = Router(name="qa_private")
    router.message.filter(F.chat.type == "private", NotAdminFilter())
    router.message.register(cmd_start, Command("start", "help"))
    router.message.register(other_command, F.text.startswith("/"))
    router.message.register(on_question, F.text)
    return router


async def on_channel_dm(message: Message, ctx: AppContext, bot: Bot) -> None:
    """Kanalning direct messages chati (Bot API 9.2): javob o'sha mavzu (topic) ichida."""
    qa = ctx.services.get("qa")
    if qa is None or not message.from_user or not message.text or message.from_user.is_bot:
        return
    answer = await qa.answer(message.from_user.id, message.text, "channel_dm")
    topic = message.direct_messages_topic.topic_id if message.direct_messages_topic else None
    await bot.send_message(chat_id=message.chat.id, text=answer, direct_messages_topic_id=topic)


def create_dm_router() -> Router:
    router = Router(name="channel_dm")
    router.message.filter(F.chat.is_direct_messages.is_(True))
    router.message.register(on_channel_dm, F.text)
    return router
