"""MongoDB hujjatlari (SPEC 10-bo'lim jadvallari). `id` — butun son, Mongo da `_id`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from app.utils.timeutil import utcnow


@dataclass(kw_only=True)
class Doc:
    __collection__: ClassVar[str] = ""
    id: int | None = None


@dataclass(kw_only=True)
class Source(Doc):
    __collection__ = "sources"
    name: str
    type: str  # rss | cisa_kev | nvd | hackernews | github
    url: str
    category: str
    trust: int = 3
    lang: str = "en"
    enabled: bool = True
    last_ok_at: datetime | None = None
    fail_count: int = 0
    last_error: str | None = None
    auto_disabled_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(kw_only=True)
class Article(Doc):
    __collection__ = "articles"
    source_id: int | None = None
    url: str
    url_hash: str
    title: str
    summary: str | None = None
    content_text: str | None = None
    published_at: datetime | None = None
    lang: str = "en"
    story_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=utcnow)


@dataclass(kw_only=True)
class Story(Doc):
    __collection__ = "stories"
    title: str
    category: str | None = None
    source_category: str | None = None
    article_count: int = 1
    first_seen: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)
    score: int | None = None
    is_breaking: bool = False
    status: str = "new"
    scored_at: datetime | None = None
    why_uz: str | None = None
    risk_flags: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class Post(Doc):
    __collection__ = "posts"
    story_id: int | None = None
    kind: str
    text_html: str = ""
    title_short: str | None = None
    hashtags: list[str] = field(default_factory=list)
    image_path: str | None = None
    image_prompt: str | None = None
    source_urls: list[str] = field(default_factory=list)
    status: str = "NEW"
    score: int | None = None
    check_report: dict[str, Any] = field(default_factory=dict)
    needs_approval: bool = False
    approval_reason: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    message_id: int | None = None
    chat_id: int | None = None
    discussion_message_id: int | None = None
    publish_key: str | None = None
    created_by: str = "ai"
    slot: str | None = None
    attempts: int = 0
    approval_sent_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(kw_only=True)
class Poll(Doc):
    __collection__ = "polls"
    post_id: int | None = None
    telegram_poll_id: str | None = None
    question: str
    options: list[str] = field(default_factory=list)
    correct_option_ids: list[int] = field(default_factory=list)
    explanation: str | None = None
    results: dict[str, Any] = field(default_factory=dict)
    total_voters: int = 0
    purpose: str = "fun"  # fun | research | quiz
    topic: str | None = None
    closed: bool = False
    closes_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(kw_only=True)
class PostMetric(Doc):
    __collection__ = "post_metrics"
    post_id: int
    ts: datetime = field(default_factory=utcnow)
    reactions: dict[str, Any] = field(default_factory=dict)
    reaction_total: int = 0
    comments: int = 0


@dataclass(kw_only=True)
class SubscriberSnapshot(Doc):
    __collection__ = "subscriber_snapshots"
    ts: datetime = field(default_factory=utcnow)
    count: int


@dataclass(kw_only=True)
class InviteLink(Doc):
    __collection__ = "invite_links"
    name: str
    url: str
    created_at: datetime = field(default_factory=utcnow)
    joins: int = 0
    leaves: int = 0


@dataclass(kw_only=True)
class MemberEvent(Doc):
    __collection__ = "member_events"
    ts: datetime = field(default_factory=utcnow)
    user_hash: str
    event: str  # join | leave
    invite_link_id: int | None = None


@dataclass(kw_only=True)
class QALog(Doc):
    __collection__ = "qa_logs"
    user_hash: str
    channel: str  # dm | comments | channel_dm
    question: str
    answer: str = ""
    flagged: bool = False
    ts: datetime = field(default_factory=utcnow)


@dataclass(kw_only=True)
class ModerationEvent(Doc):
    __collection__ = "moderation_events"
    ts: datetime = field(default_factory=utcnow)
    chat_id: int | None = None
    user_hash: str
    excerpt: str
    label: str
    action: str


@dataclass(kw_only=True)
class LLMUsage(Doc):
    __collection__ = "llm_usage"
    ts: datetime = field(default_factory=utcnow)
    role: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    ok: bool = True
    error: str | None = None


@dataclass(kw_only=True)
class AuditLog(Doc):
    __collection__ = "audit_log"
    ts: datetime = field(default_factory=utcnow)
    actor: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)


ALL_MODELS: tuple[type[Doc], ...] = (
    Source,
    Article,
    Story,
    Post,
    Poll,
    PostMetric,
    SubscriberSnapshot,
    InviteLink,
    MemberEvent,
    QALog,
    ModerationEvent,
    LLMUsage,
    AuditLog,
)
