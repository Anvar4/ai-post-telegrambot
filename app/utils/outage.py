"""Aloqa uzilishini kuzatish: qisqasi — jim; 10 daqiqadan oshsa — bitta xabar; tiklansa — bitta xabar."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger

from app.utils.security import mask_secrets
from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

NOTIFY_AFTER = timedelta(minutes=10)


class OutageTracker:
    def __init__(
        self, notify_after: timedelta = NOTIFY_AFTER, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self.notify_after = notify_after
        self.clock = clock
        self.started: datetime | None = None
        self.notified = False

    async def failure(self, ctx: AppContext, name: str, exc: BaseException) -> None:
        now = self.clock()
        reason = mask_secrets(f"{type(exc).__name__}: {exc}")[:200]
        if self.started is None:
            self.started = now
            logger.warning("Aloqa uzildi ({}): {} — bot oʻzi qayta ulanadi", name, reason)
            return
        logger.debug("Aloqa hali yoʻq ({}): {}", name, reason)
        if not self.notified and now - self.started >= self.notify_after:
            self.notified = True
            since = to_tz(self.started, ctx.settings.tz).strftime("%H:%M")
            await ctx.notifier.notify(
                f"⚠️ {since} dan beri internet/MongoDB bilan aloqa yoʻq. Bot oʻzi qayta ulanadi — "
                "aloqa tiklanganda xabar beraman.",
                key="outage",
            )

    async def success(self, ctx: AppContext) -> None:
        if self.started is None:
            return
        minutes = max(1, int((self.clock() - self.started).total_seconds() // 60))
        logger.info("Aloqa tiklandi ({} daqiqa)", minutes)
        if self.notified:
            await ctx.notifier.notify(
                f"✅ Aloqa tiklandi ({minutes} daqiqa uzilish). Bot ishlashda davom etyapti."
            )
        self.started = None
        self.notified = False


def get_tracker(ctx: AppContext) -> OutageTracker:
    tracker = ctx.services.get("outage")
    if tracker is None:
        tracker = ctx.services["outage"] = OutageTracker()
    return tracker  # type: ignore[no-any-return]
