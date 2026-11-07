"""Kanal statistikasi Telethon (admin akkaunti) orqali: post koʻrishlari, ulashishlar, koʻrishlar manbasi.

Bot API koʻrishlarni bermaydi, shuning uchun adminning Telegram akkaunti (StringSession) ishlatiladi.
Sessiya `scripts/telethon_login.py` bilan bir marta olinadi va `.env` dagi TG_SESSION da saqlanadi.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from app.pipeline.state import PostStatus
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext

MESSAGES_LIMIT = 100
FOLLOWER_SOURCES = ("followers", "obunachilar", "подписчики")


@dataclass
class MessageStat:
    message_id: int
    views: int
    forwards: int
    replies: int
    reactions: int


class StatsSource(Protocol):
    async def message_stats(self, channel_id: int, limit: int) -> list[MessageStat]: ...

    async def broadcast_stats(self, channel_id: int) -> dict[str, Any] | None: ...

    async def close(self) -> None: ...


def graph_totals(data: str) -> dict[str, int]:
    """Telegram statistika grafigi (JSON: columns + names) → har bir qator boʻyicha jami."""
    try:
        parsed = json.loads(data)
        names = parsed.get("names", {})
        out: dict[str, int] = {}
        for column in parsed.get("columns", []):
            key, values = column[0], column[1:]
            if key == "x" or key not in names:
                continue
            out[str(names[key])] = int(sum(v for v in values if isinstance(v, int | float)))
        return out
    except (ValueError, TypeError, AttributeError, IndexError):
        return {}


class ChannelStatsService:
    def __init__(self, ctx: AppContext, source_factory: Callable[[], Awaitable[StatsSource]]) -> None:
        self.ctx = ctx
        self.source_factory = source_factory

    async def collect(self) -> int:
        """Oxirgi postlar koʻrishlarini va kanal statistikasini yangilaydi; yangilangan postlar soni."""
        channel_id = self.ctx.settings.target_chat_id
        if channel_id is None:
            return 0
        source = await self.source_factory()
        try:
            stats = {s.message_id: s for s in await source.message_stats(channel_id, MESSAGES_LIMIT)}
            updated = await self._update_posts(channel_id, stats)
            try:
                broadcast = await source.broadcast_stats(channel_id)
            except Exception as exc:
                logger.info("Kanal statistikasi olinmadi: {}", exc)
                broadcast = None
            if broadcast:
                by_source = broadcast.get("views_by_source") or {}
                followers = sum(v for k, v in by_source.items() if k.lower() in FOLLOWER_SOURCES)
                broadcast["non_follower_views"] = sum(by_source.values()) - followers if by_source else None
                broadcast["updated_at"] = utcnow().isoformat()
                await self.ctx.repo.set_setting("channel_stats", broadcast)
        finally:
            await source.close()
        logger.info("Kanal statistikasi: {} ta post yangilandi", updated)
        return updated

    async def _update_posts(self, channel_id: int, stats: dict[int, MessageStat]) -> int:
        if not stats:
            return 0
        posts = await self.ctx.repo.posts.find(
            {"chat_id": channel_id, "message_id": {"$in": list(stats)}, "status": PostStatus.PUBLISHED}
        )
        for post in posts:
            s = stats[post.message_id]  # type: ignore[index]
            extra = dict(post.extra or {})
            extra.update(
                views=s.views,
                forwards=s.forwards,
                reactions_tg=s.reactions,
                comments=max(int(extra.get("comments", 0)), s.replies),
                stats_at=utcnow().isoformat(),
            )
            await self.ctx.repo.posts.update(post.id, {"extra": extra})  # type: ignore[arg-type]
        return len(posts)


class TelethonStatsSource:
    """Telethon adapteri (haqiqiy akkaunt bilan; testlarda soxta manba ishlatiladi)."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    async def connect(cls, api_id: int, api_hash: str, session: str) -> TelethonStatsSource:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(session), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                "Telethon sessiyasi yaroqsiz — scripts/telethon_login.py ni qayta ishga tushiring"
            )
        return cls(client)

    async def _entity(self, channel_id: int) -> Any:
        try:
            return await self.client.get_entity(channel_id)
        except ValueError:
            await self.client.get_dialogs()  # yangi sessiyada kanal keshda boʻlmaydi
            return await self.client.get_entity(channel_id)

    async def message_stats(self, channel_id: int, limit: int) -> list[MessageStat]:
        entity = await self._entity(channel_id)
        out = []
        async for m in self.client.iter_messages(entity, limit=limit):
            if m.views is None:
                continue
            reactions = sum(r.count for r in m.reactions.results) if m.reactions else 0
            out.append(
                MessageStat(
                    message_id=m.id,
                    views=int(m.views or 0),
                    forwards=int(m.forwards or 0),
                    replies=int(m.replies.replies) if m.replies else 0,
                    reactions=int(reactions),
                )
            )
        return out

    async def broadcast_stats(self, channel_id: int) -> dict[str, Any] | None:
        from telethon.tl.functions.stats import LoadAsyncGraphRequest
        from telethon.tl.types import StatsGraph, StatsGraphAsync

        entity = await self._entity(channel_id)
        st = await self.client.get_stats(entity)  # statistika DC sini Telethon oʻzi tanlaydi

        async def graph(g: Any) -> dict[str, int]:
            try:
                if isinstance(g, StatsGraphAsync):
                    g = await self.client(LoadAsyncGraphRequest(token=g.token))
                return graph_totals(g.json.data) if isinstance(g, StatsGraph) else {}
            except Exception:
                return {}

        def pair(v: Any) -> dict[str, float]:
            return {"current": float(v.current), "previous": float(v.previous)}

        part = st.enabled_notifications
        return {
            "period": {"min": st.period.min_date.isoformat(), "max": st.period.max_date.isoformat()},
            "followers": pair(st.followers),
            "views_per_post": pair(st.views_per_post),
            "shares_per_post": pair(st.shares_per_post),
            "notifications_pct": round(100 * part.part / part.total, 1) if part.total else None,
            "views_by_source": await graph(st.views_by_source_graph),
            "new_followers_by_source": await graph(st.new_followers_by_source_graph),
        }

    async def close(self) -> None:
        await self.client.disconnect()
