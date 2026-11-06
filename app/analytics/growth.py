"""O'sish tahlili (/growth, haftalik) va AI maslahatchi (/ask) — gpt-6-sol, statistika konteksti bilan."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from app.ai.prompts import load_prompt
from app.ai.types import BudgetExceededError, Message
from app.content.formatting import normalize_uz, sanitize_html, truncate_visible, wrap_external

if TYPE_CHECKING:
    from app.context import AppContext

REPORT_LIMIT = 3500


class GrowthService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def _stats_json(self, days: int) -> tuple[dict, str]:  # type: ignore[type-arg]
        stats = await self.ctx.service("reports").stats(days)
        return stats, json.dumps(stats, ensure_ascii=False, default=str)

    async def growth_report(self, days: int = 7) -> str:
        stats, payload = await self._stats_json(days)
        try:
            res = await self.ctx.router.complete(
                "editor",
                [
                    Message("system", load_prompt("growth"), cache=True),
                    Message("user", wrap_external("stats", payload)),
                ],
                temperature=0.4,
                max_tokens=2500,
            )
        except Exception as exc:
            logger.warning("O'sish tahlili AI siz qaytarildi: {}", exc)
            return self.ctx.service("reports").stats_text(stats) + "\n\n⚠️ AI tahlili hozir mavjud emas."
        return truncate_visible(sanitize_html(normalize_uz(res.text.strip())), REPORT_LIMIT)

    async def ask(self, question: str) -> str:
        _, payload = await self._stats_json(7)
        user = wrap_external("stats", payload) + "\n\n" + wrap_external("user", question[:3000])
        try:
            res = await self.ctx.router.complete(
                "editor",
                [Message("system", load_prompt("advisor"), cache=True), Message("user", user)],
                temperature=0.5,
                max_tokens=2000,
                essential=False,
            )
        except BudgetExceededError:
            return "⛔️ Kunlik AI budjeti tugadi — maslahatchi ertaga ishlaydi."
        except Exception as exc:
            logger.warning("Maslahatchi xatosi: {}", exc)
            return "Hozir javob bera olmayman, birozdan keyin qayta urinib koʻring."
        return truncate_visible(sanitize_html(normalize_uz(res.text.strip())), REPORT_LIMIT)
