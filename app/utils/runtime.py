"""Ishlash vaqtida o'zgaradigan sozlamalar (`/settings`, `/mode`, `/pause`) — DB dagi `settings` jadvalida."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings
    from app.db.repo import Repo

RUNTIME_DEFAULTS: dict[str, Any] = {
    "publish_mode": None,  # None -> .env dagi PUBLISH_MODE
    "paused": False,
    "slot_times": ["08:30", "13:00", "19:30"],  # kuniga nechta post va soat nechida
    "categories": ["kiber", "yangilik", "ai", "ilova", "sayt", "maslahat"],
    "polls_per_week": 2,
    "quizzes_per_week": 2,
    "digest": {"weekday": 6, "time": "20:00"},  # 6 = yakshanba
    "quiet": {"start": "23:00", "end": "07:00", "resume": "07:30"},
    "approval_timeout_action": "wait",  # wait | publish
    "approval_timeout_min": 30,
    "news_expiry_hours": 6,
    "image_review": True,
    "share_cta_every": 6,
    "breaking_min_score": 85,
    "min_score": 50,
    "category_daily_cap": 2,
    "prepare_minutes_before": 45,
}

PUBLISH_MODES = ("auto", "semi_auto", "manual")


class Runtime:
    def __init__(self, repo: Repo, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings

    async def get(self, key: str) -> Any:
        if key not in RUNTIME_DEFAULTS:
            raise KeyError(key)
        value = await self.repo.get_setting(f"rt:{key}")
        if value is not None:
            return value
        if key == "publish_mode":
            return self.settings.publish_mode
        return copy.deepcopy(RUNTIME_DEFAULTS[key])

    async def set(self, key: str, value: Any) -> None:
        if key not in RUNTIME_DEFAULTS:
            raise KeyError(key)
        await self.repo.set_setting(f"rt:{key}", value)
        await self.repo.audit("admin", "settings", key=key, value=value)

    async def all(self) -> dict[str, Any]:
        return {k: await self.get(k) for k in RUNTIME_DEFAULTS}

    async def publish_mode(self) -> str:
        return str(await self.get("publish_mode"))

    async def paused(self) -> bool:
        return bool(await self.get("paused"))
