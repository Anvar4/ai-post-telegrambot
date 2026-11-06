"""Nomli taklif havolalari: har reklama/hamkorlikdan nechta obunachi kelgani va qolgani."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.db.models import InviteLink, MemberEvent
from app.utils.security import hash_user_id
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext

JOINED = frozenset({"member", "administrator", "creator", "restricted"})
LEFT = frozenset({"left", "kicked"})
RETENTION = timedelta(days=7)


class InviteService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    def channel_id(self) -> int | None:
        return self.ctx.settings.channel_id or self.ctx.settings.target_chat_id

    async def create(self, name: str) -> str:
        chat = self.channel_id()
        if chat is None:
            raise ValueError("CHANNEL_ID sozlanmagan")
        url = await self.ctx.sender.create_invite_link(chat, name)
        await self.ctx.repo.invite_links.insert(InviteLink(name=name[:100], url=url, created_at=self.clock()))
        await self.ctx.repo.audit("admin", "invite.create", name=name)
        return url

    async def on_member_update(
        self, chat_id: int, user_id: int, old_status: str, new_status: str, invite_url: str | None
    ) -> None:
        if chat_id != self.channel_id():
            return
        user_hash = hash_user_id(user_id, self.ctx.salt)
        now = self.clock()
        repo = self.ctx.repo
        if old_status in LEFT and new_status in JOINED:
            link = await repo.invite_links.find_one({"url": invite_url}) if invite_url else None
            if link is not None:
                await repo.invite_links.update_where({"_id": link.id}, {"$inc": {"joins": 1}})
            await repo.member_events.insert(
                MemberEvent(
                    ts=now, user_hash=user_hash, event="join", invite_link_id=link.id if link else None
                )
            )
        elif old_status in JOINED and new_status in LEFT:
            last_join = await repo.member_events.find_one(
                {"user_hash": user_hash, "event": "join"}, sort=[("_id", -1)]
            )
            link_id = last_join.invite_link_id if last_join else None
            if link_id is not None:
                await repo.invite_links.update_where({"_id": link_id}, {"$inc": {"leaves": 1}})
            await repo.member_events.insert(
                MemberEvent(ts=now, user_hash=user_hash, event="leave", invite_link_id=link_id)
            )

    async def stats(self) -> list[dict[str, Any]]:
        now = self.clock()
        links = await self.ctx.repo.invite_links.find({}, sort=[("_id", 1)])
        events = await self.ctx.repo.member_events.find({"invite_link_id": {"$ne": None}})
        leaves: dict[str, list[datetime]] = {}
        for e in events:
            if e.event == "leave":
                leaves.setdefault(e.user_hash, []).append(e.ts)
        result = []
        for link in links:
            mature = [
                e
                for e in events
                if e.invite_link_id == link.id and e.event == "join" and e.ts <= now - RETENTION
            ]
            retained = sum(
                1
                for j in mature
                if not any(j.ts <= t <= j.ts + RETENTION for t in leaves.get(j.user_hash, []))
            )
            result.append(
                {
                    "name": link.name,
                    "url": link.url,
                    "joins": link.joins,
                    "leaves": link.leaves,
                    "mature_joins": len(mature),
                    "retained_7d": retained,
                }
            )
        return result
