"""RSS/Atom manbalari (feedparser)."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from app.collectors.base import FetchContext, RawItem, clean_text
from app.collectors.normalize import canonical_url
from app.db.models import Source


def _entry_time(entry: Any) -> datetime | None:
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if not ts:
        return None
    return datetime.fromtimestamp(calendar.timegm(ts), tz=UTC)


def parse(content: bytes, source: Source, fctx: FetchContext) -> list[RawItem]:
    feed = feedparser.parse(content)
    items: list[RawItem] = []
    oldest = fctx.now - fctx.max_age
    for entry in feed.entries:
        link = (entry.get("link") or "").strip()
        title = clean_text(entry.get("title"))
        if not link.startswith("http") or not title:
            continue
        published = _entry_time(entry)
        if published is not None and published < oldest:
            continue
        summary = clean_text(entry.get("summary") or entry.get("description"))[:1500]
        items.append(
            RawItem(
                url=canonical_url(link),
                title=title[:500],
                summary=summary,
                published_at=published,
                lang=source.lang or "en",
            )
        )
    return items


async def fetch(http: httpx.AsyncClient, source: Source, fctx: FetchContext) -> list[RawItem]:
    r = await http.get(source.url)
    r.raise_for_status()
    return parse(r.content, source, fctx)
