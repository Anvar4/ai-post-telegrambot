"""Bepul rasm qidirish (AIsiz): Pexels, Openverse (Flickr va b.), Wikimedia Commons.

Maqola yoki "rasmiy manba" rasmlari olinmaydi (mualliflik huquqi). Ruxsat etilgan litsenziyalar:
Pexels litsenziyasi, CC0 / Public domain / CC BY / CC BY-SA (NC va ND — yoʻq).
Avval fotobanklar (Pexels, Pixabay), keyin ochiq kolleksiyalar. Har nomzod mavzuga mosligi
(sarlavha/teg/tavsifda soʻrov soʻzi borligi) tekshiriladi — tasodifiy, gʻalati rasmlar oʻtmaydi.
Soʻrov bitta umumiy soʻzgacha qisqartirilmaydi; oxirida turkum boʻyicha aniq soʻrov ishlatiladi.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
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
PIXABAY_URL = "https://pixabay.com/api/"
PIXABAY_LICENSE_URL = "https://pixabay.com/service/license-summary/"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
# Ishonchli saytlar (DNS tekshiruvisiz); boshqa ochiq saytlar ham mumkin — faqat https va ommaviy IP
TRUSTED_HOSTS = ("images.pexels.com", "upload.wikimedia.org", "staticflickr.com", "pixabay.com")
MAX_REDIRECTS = 3
OPENVERSE_LICENSES = {"cc0": "CC0", "pdm": "Public Domain Mark", "by": "CC BY", "by-sa": "CC BY-SA"}
SITE_NAMES = {"pexels": "Pexels", "wikimedia": "Wikimedia Commons", "flickr": "Flickr", "pixabay": "Pixabay"}
ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
MIN_WIDTH, MIN_HEIGHT = 800, 450
MIN_RATIO, MAX_RATIO = 0.6, 2.4
MAX_BYTES = 8_000_000
PER_SOURCE = 10
MAX_DOWNLOADS = 12
PER_QUERY_DOWNLOADS = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
STOCK_SOURCES = frozenset({"pexels", "pixabay"})
# Mavzuga moslikni koʻrsatmaydigan umumiy soʻzlar
GENERIC_WORDS = frozenset(
    "a an the and or of for with in on at to by from new old modern digital tech technology technologies "
    "concept abstract future futuristic background image photo picture closeup close up view top "
    "illustration news update innovation business data".split()
)

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
    """Toʻliq soʻrov → (3+ soʻz boʻlsa) oxirgi ikki soʻz. Bitta umumiy soʻzgacha qisqartirilmaydi:
    "account security smartphone" → "security" qulf va politsiya rasmlarini beradi."""
    words = query.split()
    out = [" ".join(words)] if words else []
    if len(words) > 2:
        out.append(" ".join(words[-2:]))
    return list(dict.fromkeys(out))


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _word_match(q: str, t: str) -> bool:
    """Bir soʻz shakllari: car ~ cars, server ~ servers, launch ~ launches (human ≠ humanoid)."""
    if q == t or q.rstrip("s") == t.rstrip("s"):
        return True
    short, long_ = sorted((q, t), key=len)
    return len(short) >= 5 and long_.startswith(short) and len(long_) - len(short) <= 2


def topic_words(query: str) -> set[str]:
    return _tokens(query) - GENERIC_WORDS


def min_relevance(query: str) -> int:
    """3+ muhim soʻzli soʻrovda kamida 2 tasi mos kelishi kerak, aks holda 1 tasi."""
    return 2 if len(topic_words(query)) >= 3 else 1


def _trusted(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in TRUSTED_HOSTS)


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443)
    return [str(info[4][0]) for info in infos]


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
    text: str = ""  # sarlavha, teglar, tavsif — mavzuga moslikni tekshirish uchun


@dataclass
class FoundImage:
    data: bytes
    candidate: Candidate

    def credit_html(self) -> str:
        c = self.candidate
        who = f'<a href="{escape(c.page_url)}">{escape(c.author)}</a>'
        if c.source in ("pexels", "pixabay"):
            return f"📷 {who} / {SITE_NAMES[c.source]}"
        lic = escape(c.license)
        if c.license_url:
            lic = f'<a href="{escape(c.license_url)}">{lic}</a>'
        site = SITE_NAMES.get(c.site or c.source, (c.site or c.source).title())
        return f"📷 {who} / {site}, {lic}"


def relevance(cand: Candidate, query: str) -> int:
    """Nechta muhim soʻrov soʻzi rasm tavsifida bor. Tavsif yoʻq: fotobank qidiruviga ishonamiz,
    ochiq kolleksiyadagi tavsifsiz rasm — 0 (tekshirib boʻlmaydi)."""
    words = topic_words(query)
    if not words:
        return 1
    text = _tokens(cand.text)
    if not text:
        return len(words) if cand.source in STOCK_SOURCES else 0
    return sum(1 for w in words if any(_word_match(w, t) for t in text))


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
        pixabay_key: str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        resolver: Callable[[str], Awaitable[list[str]]] = _resolve,
    ) -> None:
        self.http = http
        self.pexels_key = pexels_key
        self.pixabay_key = pixabay_key
        self._sleep = sleep
        self._resolve = resolver

    @property
    def has_stock(self) -> bool:
        return bool(self.pexels_key or self.pixabay_key)

    async def candidates(self, query: str, *, stock: bool | None = None) -> list[Candidate]:
        """Pexels, Pixabay (kalit boʻlsa) → Openverse → Wikimedia, parallel; xato — shu manba boʻsh.

        `stock=True` — faqat fotobanklar, `False` — faqat ochiq kolleksiyalar, `None` — hammasi.
        """
        sources: list[Callable[[str], Awaitable[list[Candidate]]]] = []
        if stock is not False:
            if self.pexels_key:
                sources.append(self._pexels)
            if self.pixabay_key:
                sources.append(self._pixabay)
        if stock is not True:
            sources += [self._openverse, self._wikimedia]
        results = await asyncio.gather(*(self._safe(fn, query) for fn in sources))
        return [cand for group in results for cand in group]

    async def _pixabay(self, query: str) -> list[Candidate]:
        resp = await self.http.get(
            PIXABAY_URL,
            params={
                "key": self.pixabay_key or "",
                "q": query,
                "image_type": "photo",
                "orientation": "horizontal",
                "safesearch": "true",
                "per_page": PER_SOURCE,
                "min_width": MIN_WIDTH,
            },
        )
        resp.raise_for_status()
        out = []
        for hit in resp.json().get("hits", []):
            url = hit.get("largeImageURL")
            if not url or not _ratio_ok(int(hit.get("imageWidth", 0)), int(hit.get("imageHeight", 0))):
                continue
            out.append(
                Candidate(
                    source="pixabay",
                    source_id=f"pixabay:{hit.get('id')}",
                    url=str(url),
                    author=str(hit.get("user") or "Pixabay")[:80],
                    page_url=str(hit.get("pageURL") or "https://pixabay.com"),
                    license="Pixabay",
                    license_url=PIXABAY_LICENSE_URL,
                    site="pixabay",
                    text=str(hit.get("tags") or ""),
                )
            )
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
                    text=str(photo.get("alt") or ""),
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
                "category": "photograph",
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
                or not url.startswith("https://")
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
                    text=" ".join(
                        [str(item.get("title") or "")]
                        + [str(t.get("name") or "") for t in item.get("tags") or [] if isinstance(t, dict)]
                    ),
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
                "iiurlwidth": 1280,  # standart oʻlcham (nostandart — 429)
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
                    text=" ".join(
                        [
                            str(page.get("title") or "").removeprefix("File:").rsplit(".", 1)[0],
                            html_to_text(str((meta.get("ImageDescription") or {}).get("value", "")))[:300],
                        ]
                    ),
                )
            )
        return out

    async def _url_ok(self, url: str) -> bool:
        """Faqat https; ishonchli saytlardan tashqarisi — ommaviy IP (ichki tarmoqqa soʻrov yuborilmaydi)."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host:
            return False
        if _trusted(host):
            return True
        try:
            ips = await self._resolve(host)
        except Exception:
            return False
        return bool(ips) and all(_public_ip(ip) for ip in ips)

    async def _get(self, url: str) -> httpx.Response | None:
        """Yoʻnaltirishlarni (redirect) har birini tekshirib kuzatadi; 429/5xx da bir marta qayta urinadi."""
        for _ in range(MAX_REDIRECTS + 1):
            if not await self._url_ok(url):
                return None
            resp = await self.http.get(url, follow_redirects=False)
            if resp.status_code in RETRY_STATUSES:
                await self._sleep(1.5)
                resp = await self.http.get(url, follow_redirects=False)
            if resp.is_redirect and resp.headers.get("location"):
                url = str(resp.url.join(resp.headers["location"]))
                continue
            return resp
        return None

    async def download(self, cand: Candidate) -> bytes | None:
        """Ochiq https sayt, ≤ 8 MB, haqiqiy rasm va yetarli oʻlchamda."""
        try:
            resp = await self._get(cand.url)
            if resp is None:
                return None
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
        query: str | Sequence[str],
        *,
        fallback: str | None = None,
        exclude: Iterable[str] = (),
        accept: Callable[[bytes], Awaitable[bool]] | None = None,
    ) -> FoundImage | None:
        """Birinchi mos rasm. Tartib: fotobanklar (barcha soʻrovlar) → ochiq kolleksiyalar;
        har soʻrov variantlari, oxirida `fallback` (turkum) soʻrovi. Mavzuga mos boʻlmagan rasm olinmaydi."""
        queries = [query] if isinstance(query, str) else list(query)
        plan: list[str] = []
        for q in queries:
            plan += query_variants(q)
        if fallback:
            plan.append(fallback)
        plan = list(dict.fromkeys(q for q in plan if q.strip()))
        skip = set(exclude)
        state = {"tried": 0}
        passes: list[bool] = [True, False] if self.has_stock else [False]
        for stock in passes:
            for q in plan:
                if state["tried"] >= MAX_DOWNLOADS:
                    break
                found = await self._try(q, stock, skip, state, accept)
                if found is not None:
                    return found
        logger.info("Rasm topilmadi: «{}»", " | ".join(plan))
        return None

    async def _try(
        self,
        q: str,
        stock: bool,
        skip: set[str],
        state: dict[str, int],
        accept: Callable[[bytes], Awaitable[bool]] | None,
    ) -> FoundImage | None:
        cands = [c for c in await self.candidates(q, stock=stock) if c.source_id not in skip]
        need = min_relevance(q)
        scored = [(relevance(c, q), i, c) for i, c in enumerate(cands)]
        # Mos kelmaganlar tashlanadi; koʻproq soʻz mos kelgani birinchi (teng boʻlsa — manba tartibi)
        ranked = [c for r, _i, c in sorted(scored, key=lambda x: (-x[0], x[1])) if r >= need]
        if len(ranked) < len(cands):
            logger.debug("Rasm: «{}» — {} ta nomzod mavzuga mos emas", q, len(cands) - len(ranked))
        batch = ranked[: min(PER_QUERY_DOWNLOADS, MAX_DOWNLOADS - state["tried"])]
        if not batch:
            return None
        skip.update(c.source_id for c in batch)
        state["tried"] += len(batch)
        # Bir nechtasini parallel yuklab, birinchi muvofiqini (tartib boʻyicha) olamiz
        datas = await asyncio.gather(*(self.download(c) for c in batch))
        for cand, data in zip(batch, datas, strict=True):
            if data is None:
                continue
            if accept is not None and not await accept(data):
                continue
            logger.info("Rasm topildi: «{}» → {} ({})", q, cand.source_id, cand.license)
            return FoundImage(data=data, candidate=cand)
        return None
