"""Post hayot sikli: holatlar va ruxsat etilgan o'tishlar (SPEC 10-bo'lim)."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.db.models import Post
    from app.db.repo import Repo


class PostStatus(StrEnum):
    NEW = "NEW"
    SELECTED = "SELECTED"
    DRAFTED = "DRAFTED"
    CHECKED = "CHECKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class PostKind(StrEnum):
    NEWS = "news"
    ALERT = "alert"
    TOOL = "tool"
    SITE = "site"
    TIP = "tip"
    POLL = "poll"
    QUIZ = "quiz"
    DIGEST = "digest"
    QA = "qa"
    MANUAL = "manual"  # admin oʻzi yuklagan post (matn / rasm / video)


S = PostStatus

TERMINAL: frozenset[PostStatus] = frozenset({S.PUBLISHED, S.REJECTED, S.EXPIRED})
ACTIVE: frozenset[PostStatus] = frozenset(set(PostStatus) - TERMINAL - {S.FAILED})

_FORWARD: dict[PostStatus, frozenset[PostStatus]] = {
    S.NEW: frozenset({S.SELECTED}),
    S.SELECTED: frozenset({S.DRAFTED}),
    S.DRAFTED: frozenset({S.CHECKED}),
    S.CHECKED: frozenset({S.DRAFTED, S.PENDING_APPROVAL, S.SCHEDULED}),
    S.PENDING_APPROVAL: frozenset({S.SCHEDULED, S.DRAFTED}),
    S.SCHEDULED: frozenset({S.PUBLISHING, S.PENDING_APPROVAL}),
    S.PUBLISHING: frozenset({S.PUBLISHED, S.SCHEDULED}),
    S.FAILED: frozenset({S.SCHEDULED, S.PENDING_APPROVAL}),
}

_ANYWHERE = frozenset({S.REJECTED, S.FAILED, S.EXPIRED})


class InvalidTransitionError(Exception):
    pass


def can_transition(current: PostStatus | str, new: PostStatus | str) -> bool:
    current, new = PostStatus(current), PostStatus(new)
    if current in TERMINAL or current == new:
        return False
    if new in _ANYWHERE:
        return True
    return new in _FORWARD.get(current, frozenset())


async def transition(repo: Repo, post: Post, new: PostStatus, actor: str, **details: Any) -> None:
    """Holatni xotirada o'zgartiradi va audit_log ga yozadi; saqlash — chaqiruvchida (`repo.posts.save`)."""
    current = PostStatus(post.status)
    if not can_transition(current, new):
        raise InvalidTransitionError(f"post {post.id}: {current} -> {new}")
    post.status = PostStatus(new).value
    post.updated_at = utcnow()
    await repo.audit(
        actor,
        "post.status",
        post_id=post.id,
        **{"from": current.value, "to": PostStatus(new).value},
        **details,
    )
