"""Bot + scheduler ishga tushirish."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from typing import Any

import httpx
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from app.ai.providers.factory import build_clients
from app.ai.router import AIRouter
from app.bot.notify import AdminNotifier
from app.bot.sender import AiogramSender
from app.bot.setup import ALLOWED_UPDATES, build_dispatcher
from app.config import Settings, load_settings
from app.context import AppContext, set_ctx
from app.db.repo import Repo
from app.db.session import create_engine, make_sessionmaker, run_migrations
from app.logging_setup import setup_logging
from app.services import register_services
from app.utils.budget import BudgetGuard
from app.utils.runtime import Runtime
from app.utils.security import register_secret

USER_AGENT = "ITDunyosiBot/1.0 (Telegram channel content bot)"


async def _salt(settings: Settings, repo: Repo) -> str:
    if settings.hash_salt and settings.hash_salt.get_secret_value():
        return settings.hash_salt.get_secret_value()
    salt = await repo.get_setting("hash_salt")
    if not salt:
        salt = secrets.token_hex(16)
        await repo.set_setting("hash_salt", salt)
    register_secret(salt)
    return str(salt)


async def build_context(settings: Settings) -> tuple[AppContext, Bot, Any]:
    for value in settings.secret_values():
        register_secret(value)
    settings.data_path.mkdir(parents=True, exist_ok=True)
    (settings.data_path / "images").mkdir(exist_ok=True)
    await asyncio.to_thread(run_migrations, settings.database_url)
    engine = create_engine(settings.database_url)
    repo = Repo(make_sessionmaker(engine), tz=settings.tz)
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sender = AiogramSender(bot)
    notifier = AdminNotifier(sender, settings.admin_ids)
    http = httpx.AsyncClient(
        timeout=settings.http_timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    clients = build_clients(settings, http)
    budget = BudgetGuard(repo, settings.daily_budget_usd, notifier)
    router = AIRouter(
        clients.as_roles(),
        image=clients.image,
        repo=repo,
        budget=budget,
        prices=settings.model_prices,
        timeout=settings.ai_timeout,
    )
    ctx = AppContext(
        settings=settings,
        repo=repo,
        router=router,
        sender=sender,
        notifier=notifier,
        runtime=Runtime(repo, settings),
        salt=await _salt(settings, repo),
        http=http,
    )
    from app.config import env_file_warnings

    ctx.services["config_problems"] = [*env_file_warnings(), *clients.problems]
    register_services(ctx)
    from app.collectors.seed import seed_sources

    await seed_sources(repo)
    return ctx, bot, engine


async def _startup_checks(ctx: AppContext) -> None:
    problems: list[str] = list(ctx.services.get("config_problems", []))
    try:
        problems += await ctx.router.check_models()
    except Exception as exc:
        problems.append(f"Modellarni tekshirib bo'lmadi: {exc}")
    s = ctx.settings
    if s.target_chat_id is None:
        problems.append(
            "Post chiqadigan chat sozlanmagan: DRY_RUN=true bo'lsa TEST_CHANNEL_ID, aks holda CHANNEL_ID"
        )
    if not s.admin_ids:
        problems.append("ADMIN_IDS bo'sh — boshqaruv pulti hech kimga ochilmaydi")
    publisher = ctx.services.get("publisher")
    if publisher is not None:
        recovered = await publisher.recover_inflight()
        if recovered:
            logger.info("Qayta ishga tushish: {} ta PUBLISHING post tekshirildi", recovered)
    mode = await ctx.runtime.publish_mode()
    target = "🧪 test kanal" if s.dry_run else "🔴 haqiqiy kanal"
    text = f"✅ Bot ishga tushdi. Rejim: {mode}, chiqish: {target}."
    if problems:
        text += "\n\n⚠️ Sozlamalardagi muammolar:\n" + "\n".join(f"• {p}" for p in problems)
    for p in problems:
        logger.warning(p)
    await ctx.notifier.notify(text)


async def run() -> None:
    loaded, error = load_settings()
    if loaded is None:
        setup_logging("INFO")
        logger.error(error)
        sys.exit(1)
    settings = loaded
    setup_logging(settings.log_level, settings.data_path / "logs")
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN .env da yo'q. .env.example dan nusxa olib to'ldiring.")
        sys.exit(1)
    ctx, bot, engine = await build_context(settings)
    set_ctx(ctx)
    (settings.data_path / "bot.pid").write_text(str(os.getpid()), encoding="utf-8")
    dp = build_dispatcher(ctx)
    scheduler = None
    try:
        from app.scheduler.setup import setup_scheduler

        scheduler = await setup_scheduler(ctx)
        scheduler.start()
    except ImportError:
        logger.warning("Scheduler moduli topilmadi — faqat bot rejimi")
    try:
        try:
            me = await bot.me()
            ctx.services["bot_username"] = me.username or ""
        except Exception as exc:
            logger.error("Bot ma'lumotini olib bo'lmadi (token to'g'rimi?): {}", exc)
        await _startup_checks(ctx)
        logger.info("Bot polling boshlandi")
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        if ctx.http is not None:
            await ctx.http.aclose()
        await bot.session.close()
        await engine.dispose()
        set_ctx(None)
