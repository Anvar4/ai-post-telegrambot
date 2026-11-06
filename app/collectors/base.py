"""Yig'uvchilar uchun umumiy turlar."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import unescape
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from app.db.models import Source

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class RawItem:
    url: str
    title: str
    summary: str = ""
    published_at: datetime | None = None
    lang: str = "en"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchContext:
    now: datetime
    nvd_api_key: str | None = None
    github_token: str | None = None
    max_age: timedelta = timedelta(days=7)


Fetcher = Callable[["httpx.AsyncClient", "Source", FetchContext], Awaitable[list[RawItem]]]


def clean_text(html: str | None) -> str:
    """HTML teglarini olib tashlaydi, entity'larni ochadi, bo'shliqlarni siqadi."""
    if not html:
        return ""
    text = unescape(_TAG_RE.sub(" ", html))
    text = _WS_RE.sub(" ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)
