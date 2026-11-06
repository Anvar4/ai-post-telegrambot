"""Foydalanuvchi bo'yicha limit: daqiqasiga 3, kuniga 20 savol (xotirada)."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Literal

from app.utils.timeutil import to_tz

LimitStatus = Literal["ok", "minute", "day"]


class RateLimiter:
    def __init__(self, per_minute: int = 3, per_day: int = 20, tz: str = "Asia/Tashkent") -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self.tz = tz
        self._recent: defaultdict[str, deque[datetime]] = defaultdict(deque)
        self._daily: dict[str, tuple[date, int]] = {}

    def check(self, key: str, now: datetime) -> LimitStatus:
        """Limitni tekshiradi; `ok` bo'lsa so'rov hisobga olinadi."""
        day = to_tz(now, self.tz).date()
        day_key, count = self._daily.get(key, (day, 0))
        if day_key != day:
            count = 0
        if count >= self.per_day:
            return "day"
        recent = self._recent[key]
        while recent and now - recent[0] >= timedelta(seconds=60):
            recent.popleft()
        if len(recent) >= self.per_minute:
            return "minute"
        recent.append(now)
        self._daily[key] = (day, count + 1)
        return "ok"
