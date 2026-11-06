"""Dispatcher yig'ish: routerlar tartibi muhim (tasdiqlash → qo'lda post → admin → guruh → savol-javob)."""

from __future__ import annotations

from collections.abc import Callable

from aiogram import Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import (
    admin,
    admin_content,
    analytics,
    approval,
    group,
    manual,
    qa,
    settings_menu,
    updates,
)
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
        manual.create_router(),
        admin.create_router(),
        admin_content.create_router(),
        settings_menu.create_router(),
        analytics.create_router(),
        updates.create_router(),
        qa.create_dm_router(),
        group.create_router(),
        *(factory() for factory in EXTRA_ROUTERS),
        qa.create_router(),
    ]
    dp.include_routers(*routers)
    dp.errors.register(on_error)
    return dp
