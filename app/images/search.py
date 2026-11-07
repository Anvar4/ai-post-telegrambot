"""Bepul rasm qidirish (AIsiz): Pexels, Openverse (Flickr va b.), Wikimedia Commons.

Maqola yoki "rasmiy manba" rasmlari olinmaydi (mualliflik huquqi). Ruxsat etilgan litsenziyalar:
Pexels litsenziyasi, CC0 / Public domain / CC BY / CC BY-SA (NC va ND — yoʻq).
Uzun soʻrov natija bermasa qisqartiriladi, oxirida turkum boʻyicha umumiy soʻrov ishlatiladi.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger
from PIL import Image

from app.content.formatting import escape, html_to_text

PEXELS_URL = "https://api.pexels.com/v1/search"
COMMONS_URL = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_URL = "https://api.openverse.org/v1/images/"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
# Yuklab olish faqat shu saytlardan (va ularning subdomenlaridan), faqat https
ALLOWED_HOSTS = ("images.pexels.com", "upload.wikimedia.org", "staticflickr.com")
OPENVERSE_LICENSES = {"cc0": "CC0", "pdm": "Public Domain Mark", "by": "CC BY", "by-sa": "CC BY-SA"}
SITE_NAMES = {"pexels": "Pexels", "wikimedia": "Wikimedia Commons", "flickr": "Flickr"}
ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
MIN_WIDTH, MIN_HEIGHT = 800, 450
MIN_RATIO, MAX_RATIO = 0.6, 2.4
MAX_BYTES = 8_000_000
PER_SOURCE = 10
MAX_DOWNLOADS = 8
PER_QUERY_DOWNLOADS = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

_WORD_RE = re.compile(r"[a-z0-9]+")
_CC_RE = re.compile(r"^cc[ -]by(?:-sa)?[ -]\d")


def license_ok(short_name: str) -> bool:
    """Faqat CC0, Public domain, CC BY, CC BY-SA (NC/ND, GFDL va nomaʼlumlar — yoʻq)."""
    name = (short_name or "").strip().lower()
    tokens = set(_WORD_RE.findall(name))
    if not name or tokens & {"nc", "nd"}:
        return False
    if name.startswith(("cc0", "public domain", "pd")):
        return True
    return bool(_CC_RE.match(name))


def query_variants(query: str) -> list[str]:
    """Toʻliq soʻrov → birinchi/oxirgi ikki soʻz → oxirgi soʻz (odatda asosiy predmet)."""
    words = query.split()
    out = [" ".join(words)] if words else []
    if len(words) > 2:
        out += [" ".join(words[:2]), " ".join(words[-2:])]
    if len(words) > 1:
        out.append(words[-1])
    return list(dict.fromkeys(out))


def _host_ok(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _ratio_ok(width: int, height: int) -> bool:
    return width >= MIN_WIDTH and height >= MIN_HEIGHT and MIN_RATIO <= width / max(height, 1) <= MAX_RATIO


@dataclass
class Candidate:
    source: str  # pexels | wikimedia
    source_id: str  # takror ishlatmaslik uchun
    url: str  # yuklab olinadigan fayl
    author: str
    page_url: str  # rasm sahifasi (kredit havolasi)
    license: str
    license_url: str | None
    site: str = ""  # kreditdagi manba nomi (masalan, flickr)


@dataclass
class FoundImage:
    data: bytes
    candidate: Candidate

    def credit_html(self) -> str:
        c = self.candidate
        who = f'<a href="{escape(c.page_url)}">{escape(c.author)}</a>'
        if c.source == "pexels":
            return f"📷 {who} / Pexels"
        lic = escape(c.license)
        if c.license_url:
            lic = f'<a href="{escape(c.license_url)}">{lic}</a>'
        site = SITE_NAMES.get(c.site or c.source, (c.site or c.source).title())
        return f"📷 {who} / {site}, {lic}"


def _verify_image(data: bytes) -> bool:
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception:
        return False
    return _ratio_ok(*img.size)


class ImageSearch:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        pexels_key: str | None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.http = http
        self.pexels_key = pexels_key
        self._sleep = sleep

    async def candidates(self, query: str) -> list[Candidate]:
        """Pexels (kalit boʻlsa) → Openverse → Wikimedia; tarmoq xatosi — shu manba boʻsh."""
        out: list[Candidate] = []
        if self.pexels_key:
            out += await self._safe(self._pexels, query)
        out += await self._safe(self._openverse, query)
        out += await self._safe(self._wikimedia, query)
        return out

    async def _safe(self, fn: Callable[[str], Awaitable[list[Candidate]]], query: str) -> list[Candidate]:
        try:
            return await fn(query)
        except Exception as exc:
            logger.warning("Rasm qidiruvi ({}) ishlamadi: {}", fn.__name__.strip("_"), exc)
            return []

    async def _pexels(self, query: str) -> list[Candidate]:
        resp = await self.http.get(
            PEXELS_URL,
            params={"query": query, "per_page": PER_SOURCE, "orientation": "landscape"},
            headers={"Authorization": self.pexels_key or ""},
        )
        resp.raise_for_status()
        out = []
        for photo in resp.json().get("photos", []):
            src = (photo.get("src") or {}).get("large2x")
            if not src or not _ratio_ok(int(photo.get("width", 0)), int(photo.get("height", 0))):
                continue
            out.append(
                Candidate(
                    source="pexels",
                    source_id=f"pexels:{photo.get('id')}",
                    url=src,
                    author=str(photo.get("photographer") or "Pexels"),
                    page_url=str(photo.get("url") or "https://www.pexels.com"),
                    license="Pexels",
                    license_url=PEXELS_LICENSE_URL,
                )
            )
        return out

    async def _openverse(self, query: str) -> list[Candidate]:
        """Openverse: Flickr va boshqa ochiq kolleksiyalar (kalitsiz)."""
        resp = await self.http.get(
            OPENVERSE_URL,
            params={
                "q": query,
                "license": ",".join(OPENVERSE_LICENSES),
                "page_size": 20,
                "mature": "false",
                "aspect_ratio": "wide,square",
                "size": "large,medium",
            },
        )
        resp.raise_for_status()
        out = []
        for item in resp.json().get("results", []):
            code = str(item.get("license") or "")
            if code not in OPENVERSE_LICENSES:
                continue
            lic = OPENVERSE_LICENSES[code]
            if code in ("by", "by-sa") and item.get("license_version"):
                lic = f"{lic} {item['license_version']}"
            width, height = int(item.get("width") or 0), int(item.get("height") or 0)
            url = str(item.get("url") or "")
            if (
                not license_ok(lic)
                or not _host_ok(url)
                or (width and height and not _ratio_ok(width, height))
            ):
                continue
            out.append(
                Candidate(
                    source="openverse",
                    source_id=f"openverse:{item.get('id')}",
                    url=url,
                    author=str(item.get("creator") or "Openverse")[:80],
                    page_url=str(item.get("foreign_landing_url") or "https://openverse.org"),
                    license=lic,
                    license_url=item.get("license_url") or None,
                    site=str(item.get("source") or "openverse"),
                )
            )
        return out

    async def _wikimedia(self, query: str) -> list[Candidate]:
        resp = await self.http.get(
            COMMONS_URL,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": 6,
                "gsrlimit": PER_SOURCE,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 1600,
            },
        )
        resp.raise_for_status()
        pages: dict[str, Any] = (resp.json().get("query") or {}).get("pages") or {}
        out = []
        for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = str((meta.get("LicenseShortName") or {}).get("value", ""))
            width = int(info.get("thumbwidth") or info.get("width") or 0)
            height = int(info.get("thumbheight") or info.get("height") or 0)
            if info.get("mime") not in ALLOWED_MIME or not license_ok(lic) or not _ratio_ok(width, height):
                continue
            artist = html_to_text(str((meta.get("Artist") or {}).get("value", ""))).strip()
            out.append(
                Candidate(
                    source="wikimedia",
                    source_id=f"wikimedia:{page.get('pageid')}",
                    url=str(info.get("thumburl") or info.get("url")),
                    author=(artist or "Wikimedia Commons")[:80],
                    page_url=str(info.get("descriptionurl") or "https://commons.wikimedia.org"),
                    license=lic,
                    license_url=(meta.get("LicenseUrl") or {}).get("value") or None,
                )
            )
        return out

    async def download(self, cand: Candidate) -> bytes | None:
        """Faqat ruxsat etilgan saytdan, ≤ 8 MB, haqiqiy rasm va yetarli oʻlchamda."""
        if not _host_ok(cand.url):
            return None
        try:
            resp = await self.http.get(cand.url)
            if resp.status_code in RETRY_STATUSES:  # Wikimedia tez-tez soʻralganda 429 qaytaradi
                await self._sleep(1.5)
                resp = await self.http.get(cand.url)
            resp.raise_for_status()
        except Exception as exc:
            logger.info("Rasm yuklanmadi {}: {}", cand.url, exc)
            return None
        data = resp.content
        if not data or len(data) > MAX_BYTES:
            return None
        return data if await asyncio.to_thread(_verify_image, data) else None

    async def find(
        self,
        query: str,
        *,
        fallback: str | None = None,
        exclude: Iterable[str] = (),
        accept: Callable[[bytes], Awaitable[bool]] | None = None,
    ) -> FoundImage | None:
        """Birinchi mos rasm: soʻrov qisqartirilib, oxirida `fallback` (turkum) soʻrovi bilan qidiriladi."""
        skip = set(exclude)
        tried = 0
        queries = query_variants(query) + ([fallback] if fallback else [])
        for q in dict.fromkeys(queries):
            per_query = 0
            for cand in await self.candidates(q):
                if cand.source_id in skip:
                    continue
                skip.add(cand.source_id)
                if tried >= MAX_DOWNLOADS:
                    return None
                if per_query >= PER_QUERY_DOWNLOADS:
                    break
                tried += 1
                per_query += 1
                data = await self.download(cand)
                if data is None:
                    continue
                if accept is not None and not await accept(data):
                    continue
                logger.info("Rasm topildi: «{}» → {} ({})", q, cand.source_id, cand.license)
                return FoundImage(data=data, candidate=cand)
        logger.info("Rasm topilmadi: «{}»", query)
        return None
