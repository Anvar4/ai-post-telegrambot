"""Hacker News: top storylar (havolasi bor va ≥100 ball)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.collectors.base import FetchContext, RawItem
from app.collectors.normalize import canonical_url
from app.db.models import Source

TOP_N = 30
MIN_SCORE = 100
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


async def fetch(http: httpx.AsyncClient, source: Source, fctx: FetchContext) -> list[RawItem]:
    r = await http.get(source.url)
    r.raise_for_status()
    ids: list[int] = list(r.json() or [])[:TOP_N]
    sem = asyncio.Semaphore(8)

    async def one(item_id: int) -> dict[str, Any] | None:
        async with sem:
            try:
                resp = await http.get(ITEM_URL.format(id=item_id))
                resp.raise_for_status()
                data: dict[str, Any] | None = resp.json()
                return data
            except httpx.HTTPError:
                return None

    items: list[RawItem] = []
    for data in await asyncio.gather(*(one(i) for i in ids)):
        if not data or data.get("type") != "story" or not data.get("url"):
            continue
        if int(data.get("score") or 0) < MIN_SCORE:
            continue
        hn_id = data.get("id")
        items.append(
            RawItem(
                url=canonical_url(data["url"]),
                title=str(data.get("title", ""))[:500],
                summary=f"Hacker News: {data.get('score')} ball, {data.get('descendants', 0)} izoh.",
                published_at=datetime.fromtimestamp(int(data.get("time") or 0), tz=UTC)
                if data.get("time")
                else None,
                lang="en",
                extra={
                    "hn_id": hn_id,
                    "score": data.get("score"),
                    "hn_url": f"https://news.ycombinator.com/item?id={hn_id}",
                },
            )
        )
    return items
