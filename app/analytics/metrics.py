"""Metrikalar: obunachilar snapshoti, reaksiyalar, izohlar, faollik balli."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from app.db.models import Post, PostMetric, SubscriberSnapshot
from app.pipeline.state import PostKind
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext

MILESTONES = (1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000)


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
        previous = await self.latest_subscribers() if await self._has_snapshot() else None
        await self.ctx.repo.snapshots.insert(SubscriberSnapshot(ts=self.clock(), count=count))
        if previous is not None:
            for milestone in MILESTONES:
                if previous < milestone <= count:
                    await self._celebrate(milestone)
        return count

    async def _has_snapshot(self) -> bool:
        return await self.ctx.repo.snapshots.count() > 0

    async def _celebrate(self, milestone: int) -> None:
        """Marra (1000, 5000…): maxsus post va test qoralamalari — admin tasdig'i bilan (SPEC 8.4)."""
        done = list(await self.ctx.repo.get_setting("milestones_done", []))
        if milestone in done:
            return
        await self.ctx.repo.set_setting("milestones_done", [*done, milestone])
        await self.ctx.notifier.notify(
            f"🎉 Kanal {milestone} obunachiga yetdi! Maxsus post va test qoralamalari tasdiqqa yuborildi.",
            key=f"milestone:{milestone}",
        )
        pipeline = self.ctx.services.get("pipeline")
        quizzes = self.ctx.services.get("quizzes")
        try:
            if pipeline is not None:
                await pipeline.prepare_custom(
                    PostKind.TIP,
                    source_text=(
                        f"Kanal {milestone} obunachiga yetdi. Obunachilarga samimiy minnatdorchilik, "
                        "kanal nimalar haqida yozishi (IT yangiliklari, kiberxavfsizlik ogohlantirishlari, "
                        "foydali ilova va maslahatlar, soʻrovnoma va testlar), keyingi rejalar va "
                        "doʻstlarga ulashishga chaqiriq."
                    ),
                    story_title=f"{milestone} obunachi — rahmat!",
                    category="marra",
                    force_approval=True,
                )
            if quizzes is not None:
                await quizzes.create(
                    f"IT bilimlari — {milestone} obunachi marrasi uchun maxsus test", created_by="admin"
                )
        except Exception as exc:
            logger.warning("Marra kontenti tayyorlanmadi: {}", exc)

    async def latest_subscribers(self) -> int:
        snap = await self.ctx.repo.snapshots.find_one({}, sort=[("_id", -1)])
        return int(snap.count) if snap else 0

    async def _post_by_message(self, chat_id: int, message_id: int) -> Post | None:
        return await self.ctx.repo.posts.find_one({"chat_id": chat_id, "message_id": message_id})

    async def on_reaction_count(
        self, chat_id: int, message_id: int, reactions: Sequence[tuple[str, int]]
    ) -> None:
        post = await self._post_by_message(chat_id, message_id)
        if post is None:
            return
        counts = {key: int(n) for key, n in reactions}
        await self.ctx.repo.post_metrics.insert(
            PostMetric(
                post_id=post.id,  # type: ignore[arg-type]
                ts=self.clock(),
                reactions=counts,
                reaction_total=sum(counts.values()),
                comments=int((post.extra or {}).get("comments", 0)),
            )  # type: ignore[arg-type]
        )

    async def on_auto_forward(self, channel_message_id: int, discussion_message_id: int) -> None:
        post = await self.ctx.repo.posts.find_one(
            {"message_id": channel_message_id, "chat_id": {"$in": list(self._post_chats())}},
            sort=[("_id", -1)],
        )
        if post is not None:
            await self.ctx.repo.posts.update(post.id, {"discussion_message_id": discussion_message_id})  # type: ignore[arg-type]

    async def on_comment(self, root_discussion_id: int | None) -> None:
        if not root_discussion_id:
            return
        await self.ctx.repo.posts.update_where(
            {"discussion_message_id": root_discussion_id}, {"$inc": {"extra.comments": 1}}
        )

    async def reactions_by_post(self, post_ids: Sequence[int]) -> dict[int, int]:
        if not post_ids:
            return {}
        rows = await self.ctx.repo.post_metrics.find({"post_id": {"$in": list(post_ids)}}, sort=[("_id", 1)])
        latest: dict[int, int] = {}
        for m in rows:  # oxirgi yozuv ustun keladi
            latest[m.post_id] = m.reaction_total
        return latest

    async def engagement_by_post(self, post_ids: Sequence[int]) -> dict[int, float]:
        if not post_ids:
            return {}
        subs = await self.latest_subscribers()
        reactions = await self.reactions_by_post(post_ids)
        posts = await self.ctx.repo.posts.find({"_id": {"$in": list(post_ids)}})
        votes = {
            p.post_id: p.total_voters
            for p in await self.ctx.repo.polls.find({"post_id": {"$in": list(post_ids)}})
        }
        return {
            p.id: engagement_score(  # type: ignore[misc]
                reactions=reactions.get(p.id, 0),  # type: ignore[arg-type]
                comments=int((p.extra or {}).get("comments", 0)),
                poll_votes=int(votes.get(p.id) or 0),
                subscribers=subs,
            )
            for p in posts
        }
