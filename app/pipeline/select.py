"""Saralovchi: gpt-6-luna filtr → gpt-6-sol baho; slot uchun eng yaxshi story'ni tanlash."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import select

from app.ai.prompts import load_prompt
from app.ai.schemas import EditorOutput, FilterOutput
from app.ai.types import Message
from app.collectors.dedupe import title_similarity
from app.content.formatting import wrap_external
from app.content.schedule import KIND_CATEGORIES
from app.db.models import Article, Post, Source, Story
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import day_bounds, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

FILTER_BATCH = 40
TOPIC_SIMILARITY = 75
DEAD_STATUSES = (PostStatus.REJECTED, PostStatus.EXPIRED, PostStatus.FAILED)


class Selector:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    # --- baholash (har story bir marta) ---

    async def score_new(self, limit: int = 30, source_categories: tuple[str, ...] | None = None) -> int:
        now = self.clock()
        since = now - timedelta(hours=24)
        await self._filter_new(since, source_categories)
        async with self.ctx.repo.session() as s:
            q = select(Story).where(Story.status == "filtered", Story.first_seen >= since)
            if source_categories:
                q = q.where(Story.source_category.in_(source_categories))
            stories = list(
                (
                    await s.execute(
                        q.order_by(Story.article_count.desc(), Story.first_seen.desc()).limit(limit)
                    )
                ).scalars()
            )
        if not stories:
            return 0
        info = await self._story_info([st.id for st in stories])
        payload = [
            {
                "id": st.id,
                "title": st.title,
                "summary": info.get(st.id, {}).get("summary", "")[:300],
                "sources": info.get(st.id, {}).get("sources", []),
                "article_count": st.article_count,
                "filter_category": st.category,
                "kev": info.get(st.id, {}).get("kev", False),
            }
            for st in stories
        ]
        recent = await self.recent_topics(now)
        research = await self._research_context()
        user = (
            "Oxirgi 24 soatdagi voqealar:\n"
            + wrap_external("source", json.dumps(payload, ensure_ascii=False))
            + "\n\nOxirgi 7 kunda yoritilgan mavzular:\n"
            + wrap_external("source", json.dumps(recent[:60], ensure_ascii=False))
        )
        if research:
            user += "\n\nAuditoriya haqida (so'rovnomalar natijasi):\n" + wrap_external("source", research)
        res = await self.ctx.router.complete(
            "editor",
            [Message("system", load_prompt("editor"), cache=True), Message("user", user)],
            schema=EditorOutput,
            temperature=0.2,
            max_tokens=4000,
        )
        items = {it.id: it for it in res.parsed.items}
        async with self.ctx.repo.session() as s:
            for st in stories:
                story = await s.get(Story, st.id)
                if story is None:
                    continue
                it = items.get(st.id)
                story.status = "scored"
                story.scored_at = now
                if it is None:
                    story.score = 0
                    continue
                story.score = it.score
                story.category = it.category or story.category
                story.is_breaking = it.is_breaking
                story.why_uz = it.why_uz
                story.risk_flags = list(it.risk_flags)
            await s.commit()
        logger.info("Saralovchi: {} ta story baholandi", len(stories))
        return len(stories)

    async def _filter_new(self, since: datetime, source_categories: tuple[str, ...] | None) -> None:
        async with self.ctx.repo.session() as s:
            q = select(Story).where(Story.status == "new", Story.first_seen >= since)
            if source_categories:
                q = q.where(Story.source_category.in_(source_categories))
            stories = list((await s.execute(q.order_by(Story.first_seen.desc()).limit(200))).scalars())
        if not stories:
            return
        info = await self._story_info([st.id for st in stories])
        for i in range(0, len(stories), FILTER_BATCH):
            batch = stories[i : i + FILTER_BATCH]
            payload = [
                {"id": st.id, "title": st.title, "source": ", ".join(info.get(st.id, {}).get("sources", []))}
                for st in batch
            ]
            res = await self.ctx.router.complete(
                "fast",
                [
                    Message("system", load_prompt("filter"), cache=True),
                    Message("user", wrap_external("source", json.dumps(payload, ensure_ascii=False))),
                ],
                schema=FilterOutput,
                temperature=0.0,
                max_tokens=2000,
            )
            verdicts = {it.id: it for it in res.parsed.items}
            async with self.ctx.repo.session() as s:
                for st in batch:
                    story = await s.get(Story, st.id)
                    if story is None:
                        continue
                    v = verdicts.get(st.id)
                    if v is not None and not v.relevant:
                        story.status = "irrelevant"
                        continue
                    story.status = "filtered"
                    if v is not None and v.category != "boshqa":
                        story.category = v.category
                    if v is not None and v.duplicate_suspect:
                        story.risk_flags = [*story.risk_flags, "duplicate_suspect"]
                await s.commit()

    async def _story_info(self, story_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not story_ids:
            return {}
        async with self.ctx.repo.session() as s:
            rows = (
                await s.execute(
                    select(Article.story_id, Article.summary, Article.extra, Source.name)
                    .join(Source, Source.id == Article.source_id, isouter=True)
                    .where(Article.story_id.in_(story_ids))
                    .order_by(Article.id)
                )
            ).all()
        info: dict[int, dict[str, Any]] = {}
        for story_id, summary, extra, source_name in rows:
            entry = info.setdefault(story_id, {"summary": "", "sources": [], "kev": False})
            if not entry["summary"] and summary:
                entry["summary"] = summary
            if source_name and source_name not in entry["sources"]:
                entry["sources"].append(source_name)
            if (extra or {}).get("kev"):
                entry["kev"] = True
        return info

    async def _research_context(self) -> str:
        polls = self.ctx.services.get("polls")
        if polls is None:
            return ""
        try:
            return str(await polls.research_context())
        except Exception:
            return ""

    async def recent_topics(self, now: datetime, days: int = 7) -> list[str]:
        since = now - timedelta(days=days)
        async with self.ctx.repo.session() as s:
            rows = (
                await s.execute(
                    select(Post.title_short, Story.title)
                    .join(Story, Story.id == Post.story_id, isouter=True)
                    .where(Post.created_at >= since, Post.status.not_in(DEAD_STATUSES))
                )
            ).all()
        topics: list[str] = []
        for title_short, story_title in rows:
            for t in (story_title, title_short):
                if t and t not in topics:
                    topics.append(t)
        return topics

    # --- tanlash ---

    async def pick(self, kind: PostKind | str, now: datetime | None = None) -> Story | None:
        kind = PostKind(kind)
        now = now or self.clock()
        cats = KIND_CATEGORIES.get(kind)
        if not cats:
            return None
        window = timedelta(hours=24) if kind in (PostKind.NEWS, PostKind.ALERT) else timedelta(days=7)
        min_score = int(await self.ctx.runtime.get("min_score"))
        cap = int(await self.ctx.runtime.get("category_daily_cap"))
        used_today = await self._categories_today(now)
        recent = await self.recent_topics(now)
        async with self.ctx.repo.session() as s:
            candidates = list(
                (
                    await s.execute(
                        select(Story)
                        .where(
                            Story.status == "scored",
                            Story.category.in_(cats),
                            Story.score >= min_score,
                            Story.first_seen >= now - window,
                        )
                        .order_by(Story.score.desc(), Story.article_count.desc(), Story.first_seen.desc())
                        .limit(50)
                    )
                ).scalars()
            )
        for story in candidates:
            if used_today[story.category or ""] >= cap:
                continue
            if "duplicate" in (story.risk_flags or []):
                continue
            if any(title_similarity(story.title, t) >= TOPIC_SIMILARITY for t in recent):
                continue
            return story
        return None

    async def _categories_today(self, now: datetime) -> Counter[str]:
        start, end = day_bounds(now, self.ctx.settings.tz)
        async with self.ctx.repo.session() as s:
            rows = (
                await s.execute(
                    select(Post.extra).where(
                        Post.created_at >= start, Post.created_at < end, Post.status.not_in(DEAD_STATUSES)
                    )
                )
            ).scalars()
            return Counter(str((extra or {}).get("category", "")) for extra in rows)

    async def breaking_candidates(self, min_score: int = 85, now: datetime | None = None) -> list[Story]:
        now = now or self.clock()
        async with self.ctx.repo.session() as s:
            return list(
                (
                    await s.execute(
                        select(Story)
                        .where(
                            Story.status == "scored",
                            Story.is_breaking.is_(True),
                            Story.score >= min_score,
                            Story.first_seen >= now - timedelta(hours=24),
                        )
                        .order_by(Story.score.desc())
                    )
                ).scalars()
            )
