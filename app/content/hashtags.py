"""Hashtaglar: standartlar va normallashtirish."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.pipeline.state import PostKind

DEFAULT_HASHTAGS: dict[PostKind, list[str]] = {
    PostKind.ALERT: ["#kiberxavfsizlik", "#ogohlantirish"],
    PostKind.NEWS: ["#yangilik"],
    PostKind.TOOL: ["#ilova"],
    PostKind.SITE: ["#sayt"],
    PostKind.TIP: ["#maslahat"],
    PostKind.POLL: ["#sorovnoma"],
    PostKind.QUIZ: ["#test"],
    PostKind.DIGEST: ["#dayjest"],
    PostKind.QA: ["#savoljavob"],
}

MAX_HASHTAGS = 4
_STRIP_RE = re.compile(r"[\s'‘’`ʻʼ´\-.,!?#]+")


def _clean(tag: str) -> str:
    body = _STRIP_RE.sub("", tag)
    return f"#{body}" if body else ""


def normalize_hashtags(tags: Iterable[str], kind: PostKind | str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in [*DEFAULT_HASHTAGS.get(PostKind(kind), []), *tags]:
        tag = _clean(raw)
        if not tag:
            continue
        if raw.strip() and not raw.strip().startswith("#") and " " in raw.strip():
            # "Kiber xavfsizlik" -> "#Kiberxavfsizlik"
            tag = "#" + tag[1:2].upper() + tag[2:]
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= MAX_HASHTAGS:
            break
    return result
