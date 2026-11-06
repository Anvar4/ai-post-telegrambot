"""Ilova konteksti: barcha servislar bitta joyda (handlerlar va scheduler vazifalari uchun)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    import httpx

    from app.ai.router import AIRouter
    from app.bot.notify import AdminNotifier
    from app.bot.sender import TelegramSender
    from app.config import Settings
    from app.db.repo import Repo
    from app.utils.runtime import Runtime


@dataclass
class AppContext:
    settings: Settings
    repo: Repo
    router: AIRouter
    sender: TelegramSender
    notifier: AdminNotifier
    runtime: Runtime
    salt: str
    http: httpx.AsyncClient | None = None
    started_at: datetime = field(default_factory=utcnow)
    # Keyingi bosqichlarda to'ldiriladigan servislar
    services: dict[str, Any] = field(default_factory=dict)

    def service(self, name: str) -> Any:
        svc = self.services.get(name)
        if svc is None:
            raise RuntimeError(f"'{name}' servisi ishga tushirilmagan")
        return svc


_ctx: AppContext | None = None


def set_ctx(ctx: AppContext | None) -> None:
    global _ctx
    _ctx = ctx


def get_ctx() -> AppContext:
    if _ctx is None:
        raise RuntimeError("AppContext hali yaratilmagan")
    return _ctx
