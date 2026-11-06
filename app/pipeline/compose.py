"""Postni Telegram xabarlariga aylantirish (rasm + caption, uzun matn, so'rovnoma)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.content.formatting import escape, truncate_visible, visible_length
from app.content.limits import CAPTION_LIMIT, MESSAGE_LIMIT
from app.db.models import Post
from app.pipeline.state import PostKind


@dataclass
class OutboundMessage:
    kind: Literal["photo", "text", "poll"]
    text: str | None = None
    photo: bytes | None = None
    poll: dict[str, Any] | None = None


def compose(post: Post, image: bytes | None) -> list[OutboundMessage]:
    if post.kind in (PostKind.POLL, PostKind.QUIZ) and (post.extra or {}).get("poll"):
        return [OutboundMessage("poll", poll=dict(post.extra["poll"]))]
    text = (post.text_html or "").strip()
    if image:
        if visible_length(text) <= CAPTION_LIMIT:
            return [OutboundMessage("photo", text=text, photo=image)]
        caption = f"<b>{escape(post.title_short)}</b>" if post.title_short else None
        return [
            OutboundMessage("photo", text=caption, photo=image),
            OutboundMessage("text", text=truncate_visible(text, MESSAGE_LIMIT)),
        ]
    return [OutboundMessage("text", text=truncate_visible(text, MESSAGE_LIMIT))]
