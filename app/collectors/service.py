"""Yig'uvchi servis: manbalarni o'qiydi, yangi maqolalarni saqlaydi, story'larga birlashtiradi."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger
from sqlalchemy import and_, or_, select

from app.collectors import cisa_kev, github, hackernews, nvd, rss
from app.collectors.base import FetchContext, Fetcher, RawItem
from app.collectors.dedupe import attach_to_story
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
        async with self.repo.session() as s:
            sources = list(
                (
                    await s.execute(
                        select(Source).where(
                            or_(
                                Source.enabled.is_(True),
                                and_(
                                    Source.auto_disabled_at.is_not(None),
                                    Source.auto_disabled_at <= now - RETRY_DISABLED_AFTER,
                                ),
                            )
                        )
                    )
                ).scalars()
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
        added = 0
        new_story_ids: list[int] = []
        seen: set[str] = set()
        async with self.repo.session() as s:
            for item in items:
                h = url_hash(item.url)
                if h in seen:
                    continue
                seen.add(h)
                exists = await s.scalar(select(Article.id).where(Article.url_hash == h))
                if exists:
                    continue
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
                s.add(article)
                await s.flush()
                story = await attach_to_story(s, article, category=source.category, now=now)
                added += 1
                if story.article_count == 1:
                    new_story_ids.append(story.id)
            await s.commit()
        return added, new_story_ids

    async def _ok(self, source_id: int, now: datetime) -> None:
        restored = None
        async with self.repo.session() as s:
            src = await s.get(Source, source_id)
            if src is None:
                return
            src.fail_count = 0
            src.last_ok_at = now
            src.last_error = None
            if not src.enabled and src.auto_disabled_at is not None:
                src.enabled = True
                src.auto_disabled_at = None
                restored = src.name
            await s.commit()
        if restored and self.notifier:
            await self.notifier.notify(
                f"✅ Manba qayta ishlayapti va yoqildi: {restored}", key=f"src-ok:{source_id}"
            )

    async def _fail(self, source_id: int, exc: BaseException, now: datetime) -> None:
        err = mask_secrets(f"{type(exc).__name__}: {exc}")[:500]
        notify_text = None
        async with self.repo.session() as s:
            src = await s.get(Source, source_id)
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
            await s.commit()
        logger.warning("Manba xatosi {}: {}", name, err)
        await self.repo.audit("collector", "error", message=f"Manba '{name}': {err}", source_id=source_id)
        if notify_text and self.notifier:
            await self.notifier.notify(notify_text, key=f"src-off:{source_id}")
