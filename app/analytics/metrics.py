"""Metrikalar: obunachilar snapshoti, reaksiyalar, izohlar, faollik balli."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.db.models import Poll, Post, PostMetric, SubscriberSnapshot
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext


def engagement_score(*, reactions: int, comments: int, poll_votes: int, subscribers: int) -> float:
    """(reaksiyalar + 2 × izohlar + so'rovnoma ovozlari) / obunachilar × 1000 (SPEC 8)."""
    if subscribers <= 0:
        return 0.0
    return round((reactions + 2 * comments + poll_votes) / subscribers * 1000, 2)


class MetricsService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    def channel_id(self) -> int | None:
        return self.ctx.settings.channel_id or self.ctx.settings.target_chat_id

    def _post_chats(self) -> set[int]:
        s = self.ctx.settings
        return {c for c in (s.channel_id, s.test_channel_id) if c is not None}

    async def snapshot(self) -> int | None:
        chat = self.channel_id()
        if chat is None:
            return None
        count = await self.ctx.sender.member_count(chat)
        async with self.ctx.repo.session() as s:
            s.add(SubscriberSnapshot(ts=self.clock(), count=count))
            await s.commit()
        return count

    async def latest_subscribers(self) -> int:
        async with self.ctx.repo.session() as s:
            value = await s.scalar(
                select(SubscriberSnapshot.count).order_by(SubscriberSnapshot.id.desc()).limit(1)
            )
        return int(value or 0)

    async def on_reaction_count(
        self, chat_id: int, message_id: int, reactions: Sequence[tuple[str, int]]
    ) -> None:
        async with self.ctx.repo.session() as s:
            post = (
                await s.execute(select(Post).where(Post.chat_id == chat_id, Post.message_id == message_id))
            ).scalar_one_or_none()
            if post is None:
                return
            counts = {key: int(n) for key, n in reactions}
            s.add(
                PostMetric(
                    post_id=post.id,
                    ts=self.clock(),
                    reactions=counts,
                    reaction_total=sum(counts.values()),
                    comments=int((post.extra or {}).get("comments", 0)),
                )
            )
            await s.commit()

    async def on_auto_forward(self, channel_message_id: int, discussion_message_id: int) -> None:
        async with self.ctx.repo.session() as s:
            post = (
                await s.execute(
                    select(Post)
                    .where(Post.message_id == channel_message_id, Post.chat_id.in_(self._post_chats()))
                    .order_by(Post.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if post is not None:
                post.discussion_message_id = discussion_message_id
                await s.commit()

    async def on_comment(self, root_discussion_id: int | None) -> None:
        if not root_discussion_id:
            return
        async with self.ctx.repo.session() as s:
            post = (
                await s.execute(select(Post).where(Post.discussion_message_id == root_discussion_id).limit(1))
            ).scalar_one_or_none()
            if post is None:
                return
            extra = dict(post.extra or {})
            extra["comments"] = int(extra.get("comments", 0)) + 1
            post.extra = extra
            await s.commit()

    async def reactions_by_post(self, post_ids: Sequence[int]) -> dict[int, int]:
        if not post_ids:
            return {}
        async with self.ctx.repo.session() as s:
            latest = (
                select(PostMetric.post_id, func.max(PostMetric.id).label("mid"))
                .where(PostMetric.post_id.in_(post_ids))
                .group_by(PostMetric.post_id)
                .subquery()
            )
            rows = (
                await s.execute(
                    select(PostMetric.post_id, PostMetric.reaction_total).join(
                        latest, PostMetric.id == latest.c.mid
                    )
                )
            ).all()
        return {pid: int(total) for pid, total in rows}

    async def engagement_by_post(self, post_ids: Sequence[int]) -> dict[int, float]:
        if not post_ids:
            return {}
        subs = await self.latest_subscribers()
        reactions = await self.reactions_by_post(post_ids)
        async with self.ctx.repo.session() as s:
            posts = (await s.execute(select(Post.id, Post.extra).where(Post.id.in_(post_ids)))).all()
            votes = dict(
                (
                    await s.execute(select(Poll.post_id, Poll.total_voters).where(Poll.post_id.in_(post_ids)))
                ).all()
            )
        return {
            pid: engagement_score(
                reactions=reactions.get(pid, 0),
                comments=int((extra or {}).get("comments", 0)),
                poll_votes=int(votes.get(pid) or 0),
                subscribers=subs,
            )
            for pid, extra in posts
        }
