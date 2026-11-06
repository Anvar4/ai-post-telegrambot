"""Postni Telegram xabarlariga aylantirish (rasm + caption, media, uzun matn, so'rovnoma)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.content.formatting import escape, truncate_visible, visible_length
from app.content.limits import CAPTION_LIMIT, MESSAGE_LIMIT
from app.db.models import Post
from app.pipeline.state import PostKind


@dataclass
class OutboundMessage:
    kind: Literal["photo", "media", "text", "poll"]
    text: str | None = None
    photo: bytes | None = None
    poll: dict[str, Any] | None = None
    media: dict[str, str] | None = None  # {"type": photo|video|animation, "file_id": ...}


def with_credit(text: str, credit: str | None) -> str:
    """Rasm muallifi qatori — imzo (👉 …) dan oldin, boʻlmasa oxirida."""
    if not credit or credit in text:
        return text
    lines = text.rstrip().split("\n")
    if lines and lines[-1].startswith("👉"):
        return "\n".join([*lines[:-1], credit, lines[-1]])
    return text.rstrip() + "\n" + credit


def compose(post: Post, image: bytes | None) -> list[OutboundMessage]:
    if post.kind in (PostKind.POLL, PostKind.QUIZ) and (post.extra or {}).get("poll"):
        return [OutboundMessage("poll", poll=dict(post.extra["poll"]))]
    text = (post.text_html or "").strip()
    media = (post.extra or {}).get("media")
    if media:
        # Qoʻlda post: Telegram'dagi fayl; uzun matn — media dan keyin alohida xabar
        if visible_length(text) <= CAPTION_LIMIT:
            return [OutboundMessage("media", text=text or None, media=dict(media))]
        return [
            OutboundMessage("media", media=dict(media)),
            OutboundMessage("text", text=truncate_visible(text, MESSAGE_LIMIT)),
        ]
    if image:
        text = with_credit(text, (post.extra or {}).get("image_credit"))
        if visible_length(text) <= CAPTION_LIMIT:
            return [OutboundMessage("photo", text=text, photo=image)]
        caption = f"<b>{escape(post.title_short)}</b>" if post.title_short else None
        return [
            OutboundMessage("photo", text=caption, photo=image),
            OutboundMessage("text", text=truncate_visible(text, MESSAGE_LIMIT)),
        ]
    return [OutboundMessage("text", text=truncate_visible(text, MESSAGE_LIMIT))]
