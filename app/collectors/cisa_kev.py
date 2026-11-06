"""CISA Known Exploited Vulnerabilities katalogi (faol ekspluatatsiya qilinayotgan zaifliklar)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx

from app.collectors.base import FetchContext, RawItem
from app.db.models import Source

RECENT_DAYS = 3
CATALOG_URL = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
_validators: dict[str, dict[str, str]] = {}  # url -> ETag/Last-Modified (1.8 MB faylni qayta yuklamaslik)


def parse(content: bytes, source: Source, fctx: FetchContext) -> list[RawItem]:
    data = json.loads(content)
    cutoff = (fctx.now - timedelta(days=RECENT_DAYS)).date()
    items: list[RawItem] = []
    for v in data.get("vulnerabilities", []):
        try:
            added = datetime.strptime(v["dateAdded"], "%Y-%m-%d").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        if added.date() < cutoff:
            continue
        cve = v.get("cveID", "")
        title = (
            f"{cve}: {v.get('vendorProject', '')} {v.get('product', '')} — {v.get('vulnerabilityName', '')}"
        )
        summary = (
            f"{v.get('shortDescription', '')} Required action: {v.get('requiredAction', '')}. "
            f"Due date: {v.get('dueDate', '')}. "
            f"Known ransomware use: {v.get('knownRansomwareCampaignUse', '')}. "
            "Source: CISA Known Exploited Vulnerabilities catalog (actively exploited)."
        )
        items.append(
            RawItem(
                url=f"https://nvd.nist.gov/vuln/detail/{cve}",
                title=title.strip()[:500],
                summary=summary[:1500],
                published_at=added,
                lang="en",
                extra={
                    "cve": cve,
                    "vendor": v.get("vendorProject"),
                    "product": v.get("product"),
                    "kev": True,
                    "cisa_url": CATALOG_URL,
                },
            )
        )
    return items


async def fetch(http: httpx.AsyncClient, source: Source, fctx: FetchContext) -> list[RawItem]:
    headers = {}
    cached = _validators.get(source.url, {})
    if "etag" in cached:
        headers["If-None-Match"] = cached["etag"]
    if "last_modified" in cached:
        headers["If-Modified-Since"] = cached["last_modified"]
    r = await http.get(source.url, headers=headers)
    if r.status_code == 304:
        return []
    r.raise_for_status()
    validators = {}
    if r.headers.get("etag"):
        validators["etag"] = r.headers["etag"]
    if r.headers.get("last-modified"):
        validators["last_modified"] = r.headers["last-modified"]
    _validators[source.url] = validators
    return parse(r.content, source, fctx)
