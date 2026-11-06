"""Postdagi havolalar: ruxsat etilgan domenlar va ishlashini tekshirish."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import httpx

from app.collectors.normalize import domain_of

LinkStatus = Literal["ok", "dead", "unknown"]
_UNKNOWN_CODES = frozenset({401, 403, 429})
_RETRY_WITH_GET = frozenset({400, 403, 405, 501})


def allowed_domains(urls: Iterable[str]) -> set[str]:
    return {d for d in (domain_of(u) for u in urls if u and u.startswith("http")) if d}


def domain_allowed(url: str, allowed: set[str]) -> bool:
    if not url.lower().startswith(("http://", "https://")):
        return False
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in allowed)


def _classify(status: int) -> LinkStatus:
    if 200 <= status < 300:
        return "ok"
    if status in _UNKNOWN_CODES or status >= 500:
        return "unknown"
    return "dead"


async def link_status(http: httpx.AsyncClient, url: str) -> LinkStatus:
    """200 → ok; 404/410 → dead; bot bloklangan, 5xx yoki tarmoq xatosi → unknown."""
    response: httpx.Response | None = None
    try:
        response = await http.head(url, follow_redirects=True, timeout=15)
    except httpx.HTTPError:
        response = None
    if response is None or response.status_code in _RETRY_WITH_GET:
        try:
            response = await http.get(url, follow_redirects=True, timeout=20)
        except httpx.HTTPError:
            return "unknown"
    return _classify(response.status_code)
