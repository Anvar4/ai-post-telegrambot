"""Filtrlar va xatolar bilan ishlash."""

from __future__ import annotations

from typing import Any

from aiogram.filters import Filter
from aiogram.types import ErrorEvent
from loguru import logger

from app.context import AppContext
from app.utils.security import mask_secrets


class AdminFilter(Filter):
    """Faqat ADMIN_IDS dagi foydalanuvchilar."""

    async def __call__(self, event: Any, ctx: AppContext) -> bool:
        user = getattr(event, "from_user", None)
        return ctx.settings.is_admin(user.id if user else None)


class NotAdminFilter(Filter):
    async def __call__(self, event: Any, ctx: AppContext) -> bool:
        user = getattr(event, "from_user", None)
        return not ctx.settings.is_admin(user.id if user else None)


async def on_error(event: ErrorEvent, ctx: AppContext) -> bool:
    exc = event.exception
    text = mask_secrets(f"{type(exc).__name__}: {exc}")
    logger.opt(exception=exc).error("Handler xatosi: {}", text)
    try:
        await ctx.repo.audit("system", "error", message=f"handler: {text}"[:1000])
        await ctx.notifier.notify(f"❗️ Bot xatosi: {text[:500]}", key=f"handler:{type(exc).__name__}")
    except Exception:
        logger.exception("Xatoni qayd etib bo'lmadi")
    return True
