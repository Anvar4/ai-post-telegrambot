"""Umumiy DB amallari: sozlamalar, audit, xarajat, tozalash."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuditLog, LLMUsage, ModerationEvent, Post, QALog, Setting
from app.utils.timeutil import day_bounds, utcnow


class Repo:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], tz: str = "Asia/Tashkent") -> None:
        self.sessionmaker = sessionmaker
        self.tz = tz

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            yield s

    # --- sozlamalar ---

    async def get_setting(self, key: str, default: Any = None) -> Any:
        async with self.session() as s:
            row = await s.get(Setting, key)
            return default if row is None else row.value

    async def set_setting(self, key: str, value: Any) -> None:
        async with self.session() as s:
            row = await s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=value))
            else:
                row.value = value
            await s.commit()

    # --- audit va xatolar ---

    async def audit(self, actor: str, action: str, **details: Any) -> None:
        async with self.session() as s:
            s.add(AuditLog(ts=utcnow(), actor=actor, action=action, details=details))
            await s.commit()

    async def recent_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self.session() as s:
            rows = (
                (
                    await s.execute(
                        select(AuditLog)
                        .where(AuditLog.action == "error")
                        .order_by(AuditLog.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [{"ts": r.ts, **r.details} for r in rows]

    async def count_errors(self, since: datetime) -> int:
        async with self.session() as s:
            return int(
                await s.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "error", AuditLog.ts >= since)
                )
                or 0
            )

    # --- AI xarajati ---

    async def record_usage(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: float = 0.0,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        async with self.session() as s:
            s.add(
                LLMUsage(
                    ts=utcnow(),
                    role=role,
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=cost_usd,
                    ok=ok,
                    error=error[:500] if error else None,
                )
            )
            await s.commit()

    async def spent_today(self, now: datetime | None = None) -> float:
        start, end = day_bounds(now or utcnow(), self.tz)
        async with self.session() as s:
            total = await s.scalar(
                select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
                    LLMUsage.ts >= start, LLMUsage.ts < end
                )
            )
        return float(total or 0.0)

    async def usage_breakdown(self, now: datetime | None = None, days: int = 1) -> list[dict[str, Any]]:
        now = now or utcnow()
        _, end = day_bounds(now, self.tz)
        start = end - timedelta(days=days)
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(
                        LLMUsage.role,
                        LLMUsage.provider,
                        LLMUsage.model,
                        func.count(),
                        func.sum(LLMUsage.input_tokens),
                        func.sum(LLMUsage.output_tokens),
                        func.sum(LLMUsage.cost_usd),
                        func.sum(case((LLMUsage.ok.is_(False), 1), else_=0)),
                    )
                    .where(LLMUsage.ts >= start, LLMUsage.ts < end)
                    .group_by(LLMUsage.role, LLMUsage.provider, LLMUsage.model)
                    .order_by(func.sum(LLMUsage.cost_usd).desc())
                )
            ).all()
        return [
            {
                "role": r[0],
                "provider": r[1],
                "model": r[2],
                "calls": int(r[3]),
                "input_tokens": int(r[4] or 0),
                "output_tokens": int(r[5] or 0),
                "cost_usd": round(float(r[6] or 0.0), 6),
                "errors": int(r[7] or 0),
            }
            for r in rows
        ]

    # --- postlar ---

    async def get_post(self, post_id: int) -> Post | None:
        async with self.session() as s:
            return await s.get(Post, post_id)

    async def posts_by_status(self, *statuses: str, limit: int = 50) -> list[Post]:
        async with self.session() as s:
            rows = (
                (
                    await s.execute(
                        select(Post)
                        .where(Post.status.in_(statuses))
                        .order_by(Post.scheduled_at, Post.id)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    # --- tozalash ---

    async def cleanup_old(self, now: datetime | None = None, days: int = 90) -> int:
        cutoff = (now or utcnow()) - timedelta(days=days)
        async with self.session() as s:
            r1 = await s.execute(delete(QALog).where(QALog.ts < cutoff))
            r2 = await s.execute(delete(ModerationEvent).where(ModerationEvent.ts < cutoff))
            await s.commit()
        return int(getattr(r1, "rowcount", 0) or 0) + int(getattr(r2, "rowcount", 0) or 0)
