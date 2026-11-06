"""GitHub Search API: oxirgi 7 kunda yaratilib, eng ko'p yulduz olgan repolar."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.collectors.base import FetchContext, RawItem
from app.db.models import Source


async def fetch(http: httpx.AsyncClient, source: Source, fctx: FetchContext) -> list[RawItem]:
    since = (fctx.now - timedelta(days=7)).date().isoformat()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if fctx.github_token:
        headers["Authorization"] = f"Bearer {fctx.github_token}"
    r = await http.get(
        source.url,
        params={"q": f"created:>{since} stars:>50", "sort": "stars", "order": "desc", "per_page": "15"},
        headers=headers,
    )
    r.raise_for_status()
    items: list[RawItem] = []
    for repo in r.json().get("items", []):
        url = repo.get("html_url")
        if not url:
            continue
        desc = (repo.get("description") or "").strip()
        created = None
        if repo.get("created_at"):
            created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00")).astimezone(UTC)
        items.append(
            RawItem(
                url=url,
                title=f"{repo.get('full_name')}: {desc}"[:500],
                summary=(
                    f"{desc} ⭐ {repo.get('stargazers_count')} yulduz, til: {repo.get('language') or '—'}."
                )[:1500],
                published_at=created,
                lang="en",
                extra={
                    "stars": repo.get("stargazers_count"),
                    "language": repo.get("language"),
                    "homepage": repo.get("homepage") or None,
                },
            )
        )
    return items
