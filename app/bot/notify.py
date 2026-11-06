"""Adminga xabarlar: bir xil kalitli xabar soatiga ko'pi bilan 1 marta."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from loguru import logger

from app.content.formatting import escape
from app.utils.security import mask_secrets

if TYPE_CHECKING:
    from app.bot.sender import TelegramSender


class AdminNotifier:
    def __init__(
        self,
        sender: TelegramSender,
        admin_ids: Sequence[int],
        *,
        clock: Callable[[], float] = time.monotonic,
        window: float = 3600.0,
    ) -> None:
        self.sender = sender
        self.admin_ids = list(admin_ids)
        self._clock = clock
        self._window = window
        self._sent: dict[str, float] = {}

    async def notify(self, text: str, *, key: str | None = None, html: bool = False) -> None:
        if key is not None:
            now = self._clock()
            last = self._sent.get(key)
            if last is not None and now - last < self._window:
                return
            self._sent[key] = now
        body = mask_secrets(text)
        if not html:
            body = escape(body)
        for admin_id in self.admin_ids:
            try:
                await self.sender.send_message(admin_id, body[:4000])
            except Exception as exc:
                logger.warning("Adminga xabar yuborilmadi ({}): {}", admin_id, exc)
