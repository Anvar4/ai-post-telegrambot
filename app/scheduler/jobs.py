"""Rejalashtiruvchi vazifalari (APScheduler textual ref orqali chaqiriladi; kontekst `get_ctx()` dan)."""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from loguru import logger

from app.content.schedule import slot_datetime
from app.context import AppContext, get_ctx
from app.utils.security import mask_secrets
from app.utils.timeutil import to_tz, utcnow


def job(name: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[None]]]:
    """Vazifa xatosini ushlaydi: log + audit + adminga (soatiga 1 marta)."""

    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[None]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any) -> None:
            ctx = get_ctx()
            try:
                await fn(ctx, *args)
            except Exception as exc:
                text = mask_secrets(f"{type(exc).__name__}: {exc}")
                logger.opt(exception=exc).error("Vazifa {} xatosi: {}", name, text)
                try:
                    await ctx.repo.audit("scheduler", "error", message=f"{name}: {text}"[:1000])
                    await ctx.notifier.notify(f"❗️ '{name}' vazifasida xato: {text[:400]}", key=f"job:{name}")
                except Exception:
                    logger.exception("Vazifa xatosini qayd etib bo'lmadi")

        return wrapper

    return deco


@job("collect")
async def collect_job(ctx: AppContext) -> None:
    collector = ctx.services.get("collector")
    if collector is None:
        return
    stats = await collector.run_once()
    pipeline = ctx.services.get("pipeline")
    if stats.new_stories and pipeline is not None:
        await pipeline.handle_breaking()


@job("score")
async def score_job(ctx: AppContext) -> None:
    selector = ctx.services.get("selector")
    if selector is not None:
        await selector.score_new()


@job("slot")
async def slot_job(ctx: AppContext, slot_time: str) -> None:
    if slot_time not in await ctx.runtime.get("slot_times"):
        # Sozlamadan olib tashlangan (yoki eski versiyadan qolgan) vazifa — o'zini o'chiradi
        scheduler = ctx.services.get("scheduler")
        if scheduler is not None:
            with contextlib.suppress(Exception):
                scheduler.remove_job(f"slot_{slot_time.replace(':', '')}")
        return
    pipeline = ctx.services.get("pipeline")
    if pipeline is None:
        return
    local_now = to_tz(utcnow(), ctx.settings.tz)
    at = slot_datetime(local_now.date(), slot_time, ctx.settings.tz)
    if at < local_now - timedelta(hours=1):
        at += timedelta(days=1)  # tayyorlash yarim tundan oldin boshlangan bo'lsa
    await pipeline.prepare_slot(slot_time, at)


@job("publish_due")
async def publish_due_job(ctx: AppContext) -> None:
    publisher = ctx.services.get("publisher")
    if publisher is not None:
        await publisher.publish_due()


@job("expire")
async def expire_job(ctx: AppContext) -> None:
    pipeline = ctx.services.get("pipeline")
    if pipeline is not None:
        await pipeline.expire_stale()


@job("digest")
async def digest_job(ctx: AppContext) -> None:
    pipeline = ctx.services.get("pipeline")
    if pipeline is None or await ctx.runtime.paused() or await ctx.runtime.publish_mode() == "manual":
        return
    digest = await ctx.runtime.get("digest")
    today = to_tz(utcnow(), ctx.settings.tz).date()
    await pipeline.prepare_digest(slot_datetime(today, digest["time"], ctx.settings.tz))


@job("heartbeat")
async def heartbeat_job(ctx: AppContext) -> None:
    from app.utils.heartbeat import touch_heartbeat

    touch_heartbeat(ctx.settings.data_path / "heartbeat")


@job("cleanup")
async def cleanup_job(ctx: AppContext) -> None:
    removed = await ctx.repo.cleanup_old()
    if removed:
        logger.info("90 kundan eski {} ta yozuv o'chirildi", removed)


async def _call(ctx: AppContext, service: str, method: str) -> None:
    svc = ctx.services.get(service)
    if svc is not None:
        await getattr(svc, method)()


@job("backup")
async def backup_job(ctx: AppContext) -> None:
    await _call(ctx, "backup", "run")


@job("snapshot")
async def snapshot_job(ctx: AppContext) -> None:
    await _call(ctx, "metrics", "snapshot")


@job("daily_report")
async def daily_report_job(ctx: AppContext) -> None:
    await _call(ctx, "reports", "send_daily")


@job("weekly_report")
async def weekly_report_job(ctx: AppContext) -> None:
    await _call(ctx, "reports", "send_weekly")


@job("poll_close")
async def poll_close_job(ctx: AppContext) -> None:
    await _call(ctx, "polls", "close_due")


@job("channel_stats")
async def channel_stats_job(ctx: AppContext) -> None:
    await _call(ctx, "channel_stats", "collect")


@job("qa_faq")
async def qa_faq_job(ctx: AppContext) -> None:
    await _call(ctx, "qa", "weekly_faq")
