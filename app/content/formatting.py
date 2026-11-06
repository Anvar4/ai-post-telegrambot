"""Telegram HTML: tozalash, escape, uzunlik, havolalar, o'zbek apostroflari."""

from __future__ import annotations

import re
from html import escape as _html_escape
from html import unescape
from html.parser import HTMLParser

ALLOWED_TAGS = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "a",
        "code",
        "pre",
        "blockquote",
        "tg-spoiler",
    }
)
_BLOCK_TAGS = frozenset({"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "tr"})
_SAFE_SCHEMES = ("http://", "https://", "tg://")

_TAG_RE = re.compile(r"<[^>]*>")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_UZ_APOS_RE = re.compile(r"([OoGg])['‘’`ʼ´](?!s\b)")
_KNOWN_WRAP_RE = re.compile(r"<\s*/?\s*(source|user|draft|instructions|system|stats)\b[^>]*>", re.I)
_FENCE_RE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*\n?(.*?)\n?\s*```\s*$", re.S)


def escape(text: str) -> str:
    """Matnni Telegram HTML uchun xavfsiz qilish."""
    return _html_escape(text, quote=False)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool]] = []  # (tag, chiqarilganmi)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "br":
            self.out.append("\n")
            return
        if tag == "li":
            self.out.append("\n• ")
        if tag in _BLOCK_TAGS:
            self.stack.append((tag, False))
            return
        if tag == "span" and dict(attrs).get("class") == "tg-spoiler":
            tag = "tg-spoiler"
        if tag not in ALLOWED_TAGS:
            if tag not in {"script", "style", "img", "meta", "link", "input", "hr"}:
                self.stack.append((tag, False))
            return
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            if not href.lower().startswith(_SAFE_SCHEMES):
                self.stack.append((tag, False))
                return
            self.out.append(f'<a href="{_html_escape(href, quote=True)}">')
        elif tag == "blockquote" and any(k == "expandable" for k, _ in attrs):
            self.out.append("<blockquote expandable>")
        elif tag == "code" and (cls := dict(attrs).get("class") or "").startswith("language-"):
            self.out.append(f'<code class="{_html_escape(cls, quote=True)}">')
        else:
            self.out.append(f"<{tag}>")
        self.stack.append((tag, True))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "span":
            # tg-spoiler span yoki oddiy span
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] in {"tg-spoiler", "span"}:
                    tag = self.stack[i][0]
                    break
        idx = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if idx is None:
            return
        while len(self.stack) > idx:
            name, emitted = self.stack.pop()
            if emitted:
                self.out.append(f"</{name}>")
            elif name in _BLOCK_TAGS and name not in {"ul", "ol", "li"}:
                self.out.append("\n")

    def handle_data(self, data: str) -> None:
        self.out.append(escape(data))

    def result(self) -> str:
        while self.stack:
            name, emitted = self.stack.pop()
            if emitted:
                self.out.append(f"</{name}>")
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def sanitize_html(html: str) -> str:
    """Faqat Telegram qo'llab-quvvatlaydigan teglarni qoldiradi, qolganini matnga aylantiradi."""
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    return parser.result()


def html_to_text(html: str) -> str:
    return unescape(_TAG_RE.sub("", html))


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def visible_length(html: str) -> int:
    """Telegram hisoblaydigan uzunlik: teglarsiz, entity'lar ochilgan, UTF-16 birliklarda."""
    return utf16_len(html_to_text(html))


def extract_links(html: str) -> list[str]:
    links: list[str] = []
    for href in _HREF_RE.findall(html):
        url = unescape(href).strip()
        if url not in links:
            links.append(url)
    for match in _URL_RE.findall(html_to_text(html)):
        url = match.rstrip(".,;:!?)»”'")
        if url not in links:
            links.append(url)
    return links


def normalize_uz(text: str) -> str:
    """o' g' ning har xil yozilishini oʻ gʻ (U+02BB) ga keltiradi; teglar ichiga tegmaydi."""
    parts = re.split(r"(<[^>]*>)", text)
    return "".join(p if p.startswith("<") and p.endswith(">") else _UZ_APOS_RE.sub(r"\1ʻ", p) for p in parts)


def strip_code_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text.strip()


def wrap_external(tag: str, text: str) -> str:
    """Tashqi matnni teg ichiga oladi; ichidagi ma'lum teglarni neytrallaydi (prompt injection)."""
    inner = _KNOWN_WRAP_RE.sub(lambda m: "[" + m.group(0).strip("<> ") + "]", text)
    return f"<{tag}>\n{inner}\n</{tag}>"


def truncate_visible(html: str, limit: int) -> str:
    """Ko'rinadigan uzunlikni `limit` gacha qisqartiradi (oshsa formatlash olib tashlanadi)."""
    if visible_length(html) <= limit:
        return html
    text = html_to_text(html)
    out: list[str] = []
    used = 0
    for ch in text:
        size = utf16_len(ch)
        if used + size > limit - 1:
            break
        out.append(ch)
        used += size
    return escape("".join(out).rstrip()) + "…"
