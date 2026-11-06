"""Kunlik AI budjeti nazorati (SPEC 12-bo'lim)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from app.ai.types import BudgetExceededError
from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.db.repo import Repo

BudgetState = Literal["ok", "warn", "exceeded"]
WARN_RATIO = 0.8


class Notifier(Protocol):
    async def notify(self, text: str, *, key: str | None = None) -> None: ...


class BudgetGuard:
    def __init__(
        self,
        repo: Repo,
        daily_budget: float,
        notifier: Notifier | None = None,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.repo = repo
        self.daily_budget = daily_budget
        self.notifier = notifier
        self.clock = clock

    async def spent(self) -> float:
        return await self.repo.spent_today(self.clock())

    async def state(self) -> BudgetState:
        if self.daily_budget <= 0:
            return "ok"
        ratio = await self.spent() / self.daily_budget
        if ratio >= 1:
            return "exceeded"
        if ratio >= WARN_RATIO:
            return "warn"
        return "ok"

    async def ensure(self, essential: bool) -> None:
        """100% da ixtiyoriy (essential=False) chaqiruvlarni to'xtatadi; 80%/100% da 1 marta xabar."""
        state = await self.state()
        if state != "ok":
            await self._notify_once(state)
        if state == "exceeded" and not essential:
            raise BudgetExceededError("Kunlik AI budjeti tugadi")

    async def _notify_once(self, state: BudgetState) -> None:
        day = to_tz(self.clock(), self.repo.tz).date().isoformat()
        key = f"budget_notified_{state}"
        if await self.repo.get_setting(key) == day:
            return
        await self.repo.set_setting(key, day)
        spent = await self.spent()
        if state == "warn":
            text = f"⚠️ Kunlik AI budjetining 80% i sarflandi: ${spent:.2f} / ${self.daily_budget:.2f}."
        else:
            text = (
                f"⛔️ Kunlik AI budjeti tugadi: ${spent:.2f} / ${self.daily_budget:.2f}. "
                "Ertangacha faqat jadvaldagi postlar ishlaydi; "
                "savol-javob va ixtiyoriy vazifalar to'xtatildi."
            )
        if self.notifier:
            await self.notifier.notify(text, key=f"budget:{state}")
