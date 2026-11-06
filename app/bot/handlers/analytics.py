"""Admin: /stats, /growth, /link, /ask va oddiy matn → AI maslahatchi."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.handlers.admin import MENU_HANDLERS
from app.bot.middlewares import AdminFilter
from app.content.formatting import escape
from app.context import AppContext


async def stats_text(ctx: AppContext, days: int = 7) -> str:
    reports = ctx.service("reports")
    return str(reports.stats_text(await reports.stats(days)))


async def growth_text(ctx: AppContext) -> str:
    return str(await ctx.service("growth").growth_report(7))


async def cmd_stats(message: Message, command: CommandObject, ctx: AppContext) -> None:
    arg = (command.args or "7").strip()
    days = 30 if arg == "30" else 7
    await message.answer(await stats_text(ctx, days))


async def cmd_growth(message: Message, ctx: AppContext) -> None:
    await message.answer("⏳ Oʻsish tahlili tayyorlanmoqda…")
    await message.answer(await growth_text(ctx))


async def cmd_link(message: Message, command: CommandObject, ctx: AppContext) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("Foydalanish: /link &lt;nom&gt; (masalan: /link hamkor_kanal_1)")
        return
    try:
        url = await ctx.service("invites").create(name)
    except Exception as exc:
        await message.answer(f"⚠️ Havola yaratilmadi: {escape(str(exc))[:300]}")
        return
    await message.answer(
        f"🔗 <b>{escape(name)}</b>: {url}\nNatijalar: /stats (har havoladan kelgan va qolganlar)"
    )


async def _ask(message: Message, ctx: AppContext, question: str) -> None:
    if not question.strip():
        await message.answer("Savolingizni yozing: /ask &lt;savol&gt;")
        return
    await message.answer(await ctx.service("growth").ask(question))


async def cmd_ask(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _ask(message, ctx, command.args or "")


async def on_admin_text(message: Message, ctx: AppContext) -> None:
    await _ask(message, ctx, message.text or "")


MENU_HANDLERS.update({"stats": stats_text, "growth": growth_text})


def create_router() -> Router:
    router = Router(name="analytics")
    router.message.filter(AdminFilter(), F.chat.type == "private")
    router.message.register(cmd_stats, Command("stats"))
    router.message.register(cmd_growth, Command("growth"))
    router.message.register(cmd_link, Command("link"))
    router.message.register(cmd_ask, Command("ask"))
    router.message.register(on_admin_text, F.text, ~F.text.startswith("/"))
    return router
