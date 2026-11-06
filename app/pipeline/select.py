"""Saralovchi: gpt-6-luna filtr → gpt-6-sol baho; slot uchun eng yaxshi story'ni tanlash."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.ai.prompts import load_prompt
from app.ai.schemas import EditorOutput, FilterOutput
from app.ai.types import Message
from app.collectors.dedupe import title_similarity
from app.content.formatting import wrap_external
from app.content.schedule import KIND_CATEGORIES
from app.db.models import Story
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import day_bounds, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

FILTER_BATCH = 40
TOPIC_SIMILARITY = 75
DEAD_STATUSES = [PostStatus.REJECTED.value, PostStatus.EXPIRED.value, PostStatus.FAILED.value]


class Selector:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    @property
    def repo(self) -> Any:
        return self.ctx.repo

    # --- baholash (har story bir marta) ---

    async def score_new(self, limit: int = 30, source_categories: tuple[str, ...] | None = None) -> int:
        now = self.clock()
        since = now - timedelta(hours=24)
        await self._filter_new(since, source_categories)
        q: dict[str, Any] = {"status": "filtered", "first_seen": {"$gte": since}}
        if source_categories:
            q["source_category"] = {"$in": list(source_categories)}
        stories = await self.repo.stories.find(
            q, sort=[("article_count", -1), ("first_seen", -1)], limit=limit
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
        for story in stories:
            it = items.get(story.id)
            story.status = "scored"
            story.scored_at = now
            if it is None:
                story.score = 0
            else:
                story.score = it.score
                story.category = it.category or story.category
                story.is_breaking = it.is_breaking
                story.why_uz = it.why_uz
                story.risk_flags = list(it.risk_flags)
            await self.repo.stories.save(story)
        logger.info("Saralovchi: {} ta story baholandi", len(stories))
        return len(stories)

    async def _filter_new(self, since: datetime, source_categories: tuple[str, ...] | None) -> None:
        q: dict[str, Any] = {"status": "new", "first_seen": {"$gte": since}}
        if source_categories:
            q["source_category"] = {"$in": list(source_categories)}
        stories = await self.repo.stories.find(q, sort=[("first_seen", -1)], limit=200)
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
            for story in batch:
                v = verdicts.get(story.id)
                if v is not None and not v.relevant:
                    story.status = "irrelevant"
                else:
                    story.status = "filtered"
                    if v is not None and v.category != "boshqa":
                        story.category = v.category
                    if v is not None and v.duplicate_suspect:
                        story.risk_flags = [*story.risk_flags, "duplicate_suspect"]
                await self.repo.stories.save(story)

    async def _story_info(self, story_ids: list[Any]) -> dict[int, dict[str, Any]]:
        if not story_ids:
            return {}
        articles = await self.repo.articles.find({"story_id": {"$in": story_ids}}, sort=[("_id", 1)])
        source_ids = list({a.source_id for a in articles if a.source_id is not None})
        names = {s.id: s.name for s in await self.repo.sources.find({"_id": {"$in": source_ids}})}
        info: dict[int, dict[str, Any]] = {}
        for art in articles:
            entry = info.setdefault(art.story_id, {"summary": "", "sources": [], "kev": False})  # type: ignore[arg-type]
            if not entry["summary"] and art.summary:
                entry["summary"] = art.summary
            name = names.get(art.source_id)
            if name and name not in entry["sources"]:
                entry["sources"].append(name)
            if (art.extra or {}).get("kev"):
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
        posts = await self.repo.posts.find(
            {"created_at": {"$gte": now - timedelta(days=days)}, "status": {"$nin": DEAD_STATUSES}}
        )
        story_ids = [p.story_id for p in posts if p.story_id is not None]
        titles = {s.id: s.title for s in await self.repo.stories.find({"_id": {"$in": story_ids}})}
        topics: list[str] = []
        for p in posts:
            for t in (titles.get(p.story_id), p.title_short):
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
        enabled = await self._enabled_categories()
        if enabled is not None:
            cats = tuple(c for c in cats if c in enabled)
            if not cats:
                return None
        window = timedelta(hours=24) if kind in (PostKind.NEWS, PostKind.ALERT) else timedelta(days=7)
        min_score = int(await self.ctx.runtime.get("min_score"))
        cap = int(await self.ctx.runtime.get("category_daily_cap"))
        used_today = await self._categories_today(now)
        recent = await self.recent_topics(now)
        candidates = await self.repo.stories.find(
            {
                "status": "scored",
                "category": {"$in": list(cats)},
                "score": {"$gte": min_score},
                "first_seen": {"$gte": now - window},
            },
            sort=[("score", -1), ("article_count", -1), ("first_seen", -1)],
            limit=50,
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

    async def _enabled_categories(self) -> set[str] | None:
        try:
            cats = await self.ctx.runtime.get("categories")
        except KeyError:
            return None
        return set(cats) if cats is not None else None

    async def _categories_today(self, now: datetime) -> Counter[str]:
        start, end = day_bounds(now, self.ctx.settings.tz)
        posts = await self.repo.posts.find(
            {"created_at": {"$gte": start, "$lt": end}, "status": {"$nin": DEAD_STATUSES}}
        )
        return Counter(str((p.extra or {}).get("category", "")) for p in posts)

    async def breaking_candidates(self, min_score: int = 85, now: datetime | None = None) -> list[Story]:
        now = now or self.clock()
        return list(
            await self.repo.stories.find(
                {
                    "status": "scored",
                    "is_breaking": True,
                    "score": {"$gte": min_score},
                    "first_seen": {"$gte": now - timedelta(hours=24)},
                },
                sort=[("score", -1)],
            )
        )
