"""Dublikatlar: sarlavha o'xshashligi (rapidfuzz ≥ 85) + 48 soatlik oyna → bitta story."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article, Story

SIMILARITY_THRESHOLD = 85
STORY_WINDOW = timedelta(hours=48)
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", title.lower())).strip()


def title_similarity(a: str, b: str) -> float:
    return float(fuzz.token_sort_ratio(normalize_title(a), normalize_title(b)))


async def attach_to_story(
    session: AsyncSession, article: Article, *, category: str | None, now: datetime
) -> Story:
    """Maqolani mos story ga biriktiradi yoki yangisini yaratadi (commit qilmaydi)."""
    candidates = (
        (await session.execute(select(Story).where(Story.first_seen >= now - STORY_WINDOW))).scalars().all()
    )
    best: Story | None = None
    best_score = 0.0
    for story in candidates:
        score = title_similarity(article.title, story.title)
        if score > best_score:
            best, best_score = story, score
    if best is not None and best_score >= SIMILARITY_THRESHOLD:
        best.article_count += 1
        best.last_seen = now
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
    session.add(story)
    await session.flush()
    article.story_id = story.id
    return story
