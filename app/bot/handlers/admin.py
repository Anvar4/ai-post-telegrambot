"""Admin pulti: /start, /status, /mode, /pause, /resume, /budget, /logs, /id va menyu."""

from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import MenuCB, main_menu
from app.bot.middlewares import AdminFilter
from app.content.formatting import escape
from app.context import AppContext
from app.pipeline.state import PostStatus
from app.utils.runtime import PUBLISH_MODES
from app.utils.timeutil import to_tz, utcnow

HELP = """<b>IT Dunyosi — boshqaruv pulti</b>

/status — bot holati, navbat, xarajat
/queue — rejadagi va tasdiq kutayotgan postlar
/post &lt;mavzu yoki havola&gt; — darhol post tayyorlash
/poll [mavzu], /quiz [mavzu] — so'rovnoma yoki test
/digest — haftalik dayjest
/sources — manbalar
/mode auto | semi_auto | manual — nashr rejimi
/pause, /resume — avtomatik nashrni to'xtatish/davom ettirish
/stats [7|30] — statistika
/growth — o'sish hisoboti va tavsiyalar
/link &lt;nom&gt; — nomli taklif havolasi
/budget — AI xarajati
/settings — sozlamalar
/ask &lt;savol&gt; yoki oddiy matn — AI maslahatchi
/logs — oxirgi xatolar
/id — chat ID"""


async def status_text(ctx: AppContext) -> str:
    s = ctx.settings
    mode = await ctx.runtime.publish_mode()
    paused = await ctx.runtime.paused()
    spent = await ctx.repo.spent_today()
    target = s.target_chat_id
    out_line = (
        f"🧪 DRY_RUN → test kanal (<code>{target}</code>)"
        if s.dry_run
        else f"🔴 JONLI → kanal (<code>{target}</code>)"
    )
    if target is None:
        out_line += " ⚠️ chat ID sozlanmagan"
    models = ", ".join(f"{k}={escape(v)}" for k, v in ctx.router.describe().items())
    pending = await ctx.repo.posts_by_status(PostStatus.PENDING_APPROVAL, limit=100)
    queue = await ctx.repo.posts_by_status(PostStatus.SCHEDULED, limit=3)
    lines = [
        "🤖 <b>IT Dunyosi bot holati</b>",
        f"Rejim: <b>{mode}</b> · {'⏸ toʻxtatilgan' if paused else '▶️ ishlayapti'}",
        out_line,
        f"Modellar: {models}",
        f"Bugungi xarajat: ${spent:.2f} / ${s.daily_budget_usd:.2f}",
        f"Tasdiq kutmoqda: {len(pending)}",
        "<b>Navbat (keyingi 3):</b>",
    ]
    if not queue:
        lines.append(" — boʻsh")
    for p in queue:
        when = to_tz(p.scheduled_at, s.tz).strftime("%d.%m %H:%M") if p.scheduled_at else "—"
        lines.append(f" • {when} [{p.kind}] {escape((p.title_short or '')[:60])}")
    uptime = utcnow() - ctx.started_at
    lines.append(f"Ishlash vaqti: {timedelta(seconds=int(uptime.total_seconds()))!s}")
    return "\n".join(lines)


async def budget_text(ctx: AppContext) -> str:
    today = await ctx.repo.usage_breakdown(days=1)
    week = await ctx.repo.usage_breakdown(days=7)
    spent = await ctx.repo.spent_today()
    lines = [f"💰 <b>AI xarajati</b>\nBugun: ${spent:.4f} / ${ctx.settings.daily_budget_usd:.2f}"]
    if today:
        lines.append("<b>Bugun, rol bo'yicha:</b>")
        for r in today:
            lines.append(
                f" • {r['role']} · {escape(r['provider'])}/{escape(r['model'])}: {r['calls']} ta, "
                f"${r['cost_usd']:.4f}" + (f", xato {r['errors']}" if r["errors"] else "")
            )
    week_total = sum(r["cost_usd"] for r in week)
    lines.append(f"7 kun jami: ${week_total:.4f}")
    by_provider: dict[str, float] = {}
    for r in week:
        by_provider[r["provider"]] = by_provider.get(r["provider"], 0.0) + r["cost_usd"]
    for prov, cost in sorted(by_provider.items(), key=lambda x: -x[1]):
        lines.append(f" • {escape(prov)}: ${cost:.4f}")
    return "\n".join(lines)


async def logs_text(ctx: AppContext) -> str:
    errors = await ctx.repo.recent_errors(limit=10)
    if not errors:
        return "✅ Oxirgi xatolar yoʻq."
    lines = ["🧾 <b>Oxirgi xatolar</b>"]
    for e in errors:
        ts = to_tz(e["ts"], ctx.settings.tz).strftime("%d.%m %H:%M")
        lines.append(f"• {ts} — {escape(str(e.get('message', ''))[:300])}")
    return "\n".join(lines)


async def cmd_start(message: Message, ctx: AppContext) -> None:
    await message.answer(HELP, reply_markup=main_menu())


async def cmd_status(message: Message, ctx: AppContext) -> None:
    await message.answer(await status_text(ctx))


async def cmd_mode(message: Message, command: CommandObject, ctx: AppContext) -> None:
    value = (command.args or "").strip()
    if value not in PUBLISH_MODES:
        current = await ctx.runtime.publish_mode()
        await message.answer(f"Joriy rejim: <b>{current}</b>\nFoydalanish: /mode auto | semi_auto | manual")
        return
    await ctx.runtime.set("publish_mode", value)
    await message.answer(f"✅ Nashr rejimi: <b>{value}</b>")


async def cmd_pause(message: Message, ctx: AppContext) -> None:
    await ctx.runtime.set("paused", True)
    await message.answer("⏸ Avtomatik nashr toʻxtatildi. Davom ettirish: /resume")


async def cmd_resume(message: Message, ctx: AppContext) -> None:
    await ctx.runtime.set("paused", False)
    await message.answer("▶️ Avtomatik nashr davom etmoqda.")


async def cmd_budget(message: Message, ctx: AppContext) -> None:
    await message.answer(await budget_text(ctx))


async def cmd_logs(message: Message, ctx: AppContext) -> None:
    await message.answer(await logs_text(ctx))


async def cmd_id(message: Message, ctx: AppContext) -> None:
    user_id = message.from_user.id if message.from_user else "—"
    await message.answer(f"Chat ID: <code>{message.chat.id}</code>\nSizning ID: <code>{user_id}</code>")


MENU_HANDLERS = {
    "status": status_text,
    "budget": budget_text,
    "logs": logs_text,
}


async def on_menu(call: CallbackQuery, callback_data: MenuCB, ctx: AppContext) -> None:
    builder = MENU_HANDLERS.get(callback_data.action) or ctx.services.get(f"menu:{callback_data.action}")
    await call.answer()
    if builder is None or call.message is None:
        return
    await call.message.answer(await builder(ctx))


def create_router() -> Router:
    router = Router(name="admin")
    router.message.filter(AdminFilter())
    router.callback_query.filter(AdminFilter())
    # /id istalgan chatda ishlaydi (guruh va kanal ID sini olish uchun)
    router.message.register(cmd_id, Command("id"))
    private = F.chat.type == "private"
    router.message.register(cmd_start, Command("start", "help"), private)
    router.message.register(cmd_status, Command("status"), private)
    router.message.register(cmd_mode, Command("mode"), private)
    router.message.register(cmd_pause, Command("pause"), private)
    router.message.register(cmd_resume, Command("resume"), private)
    router.message.register(cmd_budget, Command("budget"), private)
    router.message.register(cmd_logs, Command("logs"), private)
    router.callback_query.register(on_menu, MenuCB.filter())
    return router
