"""Yig'uvchi servis: manbalarni o'qiydi, yangi maqolalarni saqlaydi, story'larga birlashtiradi."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from app.collectors import cisa_kev, github, hackernews, nvd, rss
from app.collectors.base import FetchContext, Fetcher, RawItem
from app.collectors.dedupe import STORY_WINDOW, StoryBatch, attach_to_story
from app.collectors.normalize import url_hash
from app.db.models import Article, Source
from app.utils.security import mask_secrets
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.db.repo import Repo

FETCHERS: dict[str, Fetcher] = {
    "rss": rss.fetch,
    "cisa_kev": cisa_kev.fetch,
    "nvd": nvd.fetch,
    "hackernews": hackernews.fetch,
    "github": github.fetch,
}
MAX_FAILS = 3
RETRY_DISABLED_AFTER = timedelta(hours=6)


@dataclass
class CollectStats:
    new_articles: int = 0
    new_stories: int = 0
    failed_sources: int = 0
    new_story_ids: list[int] = field(default_factory=list)


class CollectorService:
    def __init__(
        self,
        repo: Repo,
        http: httpx.AsyncClient,
        notifier: Any,
        *,
        nvd_api_key: str | None = None,
        github_token: str | None = None,
        clock: Callable[[], datetime] = utcnow,
        concurrency: int = 5,
    ) -> None:
        self.repo = repo
        self.http = http
        self.notifier = notifier
        self.nvd_api_key = nvd_api_key
        self.github_token = github_token
        self.clock = clock
        self.concurrency = concurrency
        self.last_run: datetime | None = None

    async def run_once(self) -> CollectStats:
        now = self.clock()
        sources = await self.repo.sources.find(
            {
                "$or": [
                    {"enabled": True},
                    {"auto_disabled_at": {"$ne": None, "$lte": now - RETRY_DISABLED_AFTER}},
                ]
            },
            sort=[("_id", 1)],
        )
        fctx = FetchContext(now=now, nvd_api_key=self.nvd_api_key, github_token=self.github_token)
        sem = asyncio.Semaphore(self.concurrency)

        async def one(source: Source) -> list[RawItem]:
            fetcher = FETCHERS.get(source.type)
            if fetcher is None:
                raise ValueError(f"noma'lum manba turi: {source.type}")
            async with sem:
                return await fetcher(self.http, source, fctx)

        results = await asyncio.gather(*(one(src) for src in sources), return_exceptions=True)
        stats = CollectStats()
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, BaseException):
                stats.failed_sources += 1
                await self._fail(source.id, result, now)
                continue
            await self._ok(source.id, now)
            articles, story_ids = await self._store(source, result, now)
            stats.new_articles += articles
            stats.new_stories += len(story_ids)
            stats.new_story_ids.extend(story_ids)
        self.last_run = now
        logger.info(
            "Yig'ish: {} yangi maqola, {} yangi story, {} manba xatosi",
            stats.new_articles,
            stats.new_stories,
            stats.failed_sources,
        )
        return stats

    async def _store(self, source: Source, items: list[RawItem], now: datetime) -> tuple[int, list[int]]:
        """Paketli saqlash: bir nechta so'rov bilan (har maqola uchun alohida so'rov emas)."""
        by_hash: dict[str, RawItem] = {}
        for item in items:
            by_hash.setdefault(url_hash(item.url), item)
        if not by_hash:
            return 0, []
        existing = {a.url_hash for a in await self.repo.articles.find({"url_hash": {"$in": list(by_hash)}})}
        fresh = [(h, it) for h, it in by_hash.items() if h not in existing]
        if not fresh:
            return 0, []
        candidates = await self.repo.stories.find({"first_seen": {"$gte": now - STORY_WINDOW}})
        batch = StoryBatch(ids=iter(await self.repo.next_ids("stories", len(fresh))))
        articles: list[Article] = []
        for h, item in fresh:
            article = Article(
                source_id=source.id,
                url=item.url,
                url_hash=h,
                title=item.title,
                summary=item.summary,
                published_at=item.published_at,
                lang=item.lang,
                extra=item.extra,
                fetched_at=now,
            )
            await attach_to_story(
                self.repo, article, category=source.category, now=now, candidates=candidates, batch=batch
            )
            articles.append(article)
        await batch.flush(self.repo)
        added = await self.repo.articles.insert_many(articles)
        return added, [s.id for s in batch.new]  # type: ignore[misc]

    async def _ok(self, source_id: int | None, now: datetime) -> None:
        src = await self.repo.sources.get(source_id)
        if src is None:
            return
        restored = None
        src.fail_count = 0
        src.last_ok_at = now
        src.last_error = None
        if not src.enabled and src.auto_disabled_at is not None:
            src.enabled = True
            src.auto_disabled_at = None
            restored = src.name
        await self.repo.sources.save(src)
        if restored and self.notifier:
            await self.notifier.notify(
                f"✅ Manba qayta ishlayapti va yoqildi: {restored}", key=f"src-ok:{source_id}"
            )

    async def _fail(self, source_id: int | None, exc: BaseException, now: datetime) -> None:
        err = mask_secrets(f"{type(exc).__name__}: {exc}")[:500]
        notify_text = None
        src = await self.repo.sources.get(source_id)
        if src is None:
            return
        src.fail_count += 1
        src.last_error = err
        if src.enabled and src.fail_count >= MAX_FAILS:
            src.enabled = False
            src.auto_disabled_at = now
            notify_text = (
                f"⚠️ Manba {MAX_FAILS} marta ketma-ket xato berdi va vaqtincha o'chirildi: "
                f"{src.name}\nXato: {err}\n6 soatdan keyin qayta urinib ko'riladi. /sources"
            )
        elif not src.enabled and src.auto_disabled_at is not None:
            src.auto_disabled_at = now  # qayta urinish ham muvaffaqiyatsiz — taymer yangilanadi
        name = src.name
        await self.repo.sources.save(src)
        logger.warning("Manba xatosi {}: {}", name, err)
        await self.repo.audit("collector", "error", message=f"Manba '{name}': {err}", source_id=source_id)
        if notify_text and self.notifier:
            await self.notifier.notify(notify_text, key=f"src-off:{source_id}")
