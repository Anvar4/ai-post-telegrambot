"""Dispatcher yig'ish: routerlar tartibi muhim (admin → tasdiqlash → update'lar → guruh → savol-javob)."""

from __future__ import annotations

from collections.abc import Callable

from aiogram import Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import admin, admin_content, approval, qa
from app.bot.middlewares import on_error
from app.context import AppContext

# Keyingi bosqichlar o'z routerlarini shu ro'yxatga qo'shadi
EXTRA_ROUTERS: list[Callable[[], Router]] = []

ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "callback_query",
    "poll",
    "chat_member",
    "my_chat_member",
    "message_reaction_count",
]


def build_dispatcher(ctx: AppContext) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["ctx"] = ctx
    routers = [
        approval.create_router(),
        admin.create_router(),
        admin_content.create_router(),
        *(factory() for factory in _router_factories()),
        qa.create_router(),
    ]
    dp.include_routers(*routers)
    dp.errors.register(on_error)
    return dp


def _router_factories() -> list[Callable[[], Router]]:
    factories: list[Callable[[], Router]] = []
    try:
        from app.bot.handlers import updates  # type: ignore[attr-defined]

        factories.append(updates.create_router)
    except ImportError:
        pass
    try:
        from app.bot.handlers import group  # type: ignore[attr-defined]

        factories.append(group.create_router)
    except ImportError:
        pass
    return [*factories, *EXTRA_ROUTERS]
