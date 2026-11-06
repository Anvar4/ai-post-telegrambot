"""Dublikatlar: sarlavha o'xshashligi (rapidfuzz ≥ 85) + 48 soatlik oyna → bitta story."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from app.db.models import Article, Story

if TYPE_CHECKING:
    from app.db.repo import Repo

SIMILARITY_THRESHOLD = 85
STORY_WINDOW = timedelta(hours=48)
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", title.lower())).strip()


def title_similarity(a: str, b: str) -> float:
    return float(fuzz.token_sort_ratio(normalize_title(a), normalize_title(b)))


@dataclass
class StoryBatch:
    """Paketli rejim: yangi va o'zgargan story'lar xotirada yig'iladi, `flush` da bir martada yoziladi."""

    ids: Iterator[int]
    new: list[Story] = field(default_factory=list)
    touched: dict[int, Story] = field(default_factory=dict)

    async def flush(self, repo: Repo) -> None:
        await repo.stories.insert_many(self.new)
        new_ids = {s.id for s in self.new}
        for story in self.touched.values():
            if story.id not in new_ids:
                await repo.stories.update(
                    story.id,  # type: ignore[arg-type]
                    {"article_count": story.article_count, "last_seen": story.last_seen},
                )


async def attach_to_story(
    repo: Repo,
    article: Article,
    *,
    category: str | None,
    now: datetime,
    candidates: list[Story] | None = None,
    batch: StoryBatch | None = None,
) -> Story:
    """Maqolani mos story ga biriktiradi yoki yangisini yaratadi (maqolaning o'zi saqlanmaydi).

    `candidates` — 48 soatlik oyna keshi; `batch` berilsa yozuvlar `batch.flush()` gacha kechiktiriladi.
    """
    if candidates is None:
        candidates = await repo.stories.find({"first_seen": {"$gte": now - STORY_WINDOW}})
    best: Story | None = None
    best_score = 0.0
    for story in candidates:
        if story.first_seen < now - STORY_WINDOW:
            continue
        score = title_similarity(article.title, story.title)
        if score > best_score:
            best, best_score = story, score
    if best is not None and best_score >= SIMILARITY_THRESHOLD:
        best.article_count += 1
        best.last_seen = now
        if batch is not None:
            batch.touched[best.id] = best  # type: ignore[index]
        else:
            await repo.stories.update(
                best.id,  # type: ignore[arg-type]
                {"article_count": best.article_count, "last_seen": now},
            )
        article.story_id = best.id
        return best
    story = Story(
        title=article.title,
        source_category=category,
        first_seen=now,
        last_seen=now,
        article_count=1,
        status="new",
    )
    if batch is not None:
        story.id = next(batch.ids)
        batch.new.append(story)
    else:
        await repo.stories.insert(story)
    candidates.append(story)
    article.story_id = story.id
    return story
