"""Maqola matnini olish (trafilatura) — faqat tahlil va fakt-tekshiruv uchun, kanalga ko'chirilmaydi."""

from __future__ import annotations

import asyncio

import httpx
import trafilatura
from loguru import logger

MAX_CHARS = 30_000


async def extract_text(http: httpx.AsyncClient, url: str, max_chars: int = MAX_CHARS) -> str | None:
    try:
        r = await http.get(url)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.debug("Matn olinmadi {}: {}", url, exc)
        return None
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "xml" not in ctype:
        return None
    html = r.text
    text = await asyncio.to_thread(
        trafilatura.extract, html, include_comments=False, include_tables=False, url=url
    )
    if not text:
        return None
    return text[:max_chars]
