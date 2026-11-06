"""SQLAlchemy 2 modellari (SPEC 10-bo'lim)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.timeutil import utcnow


class UTCDateTime(TypeDecorator[datetime]):
    """Aware datetime qabul qiladi, UTC (naive) saqlaydi, aware UTC qaytaradi."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: UTCDateTime,
        dict[str, Any]: JSON,
        list[Any]: JSON,
        list[str]: JSON,
        list[int]: JSON,
    }


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30))  # rss | cisa_kev | nvd | hackernews | github
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    category: Mapped[str] = mapped_column(String(50))
    trust: Mapped[int] = mapped_column(Integer, default=3)
    lang: Mapped[str] = mapped_column(String(10), default="en")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(2000))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1000))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    lang: Mapped[str] = mapped_column(String(10), default="en")
    story_id: Mapped[int | None] = mapped_column(
        ForeignKey("stories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(1000))
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    article_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_breaking: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    scored_at: Mapped[datetime | None] = mapped_column(nullable=True)
    why_uz: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_flags: Mapped[list[str]] = mapped_column(default=list)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int | None] = mapped_column(ForeignKey("stories.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    text_html: Mapped[str] = mapped_column(Text, default="")
    title_short: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hashtags: Mapped[list[str]] = mapped_column(default=list)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_urls: Mapped[list[str]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discussion_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    publish_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_by: Mapped[str] = mapped_column(String(10), default="ai")
    slot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    approval_sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=True)
    telegram_poll_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question: Mapped[str] = mapped_column(String(400))
    options: Mapped[list[str]] = mapped_column(default=list)
    correct_option_ids: Mapped[list[int]] = mapped_column(default=list)
    explanation: Mapped[str | None] = mapped_column(String(400), nullable=True)
    results: Mapped[dict[str, Any]] = mapped_column(default=dict)
    total_voters: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str] = mapped_column(String(20), default="fun")  # fun | research | quiz
    topic: Mapped[str | None] = mapped_column(String(200), nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closes_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PostMetric(Base):
    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    reactions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reaction_total: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)


class SubscriberSnapshot(Base):
    __tablename__ = "subscriber_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    count: Mapped[int] = mapped_column(Integer)


class InviteLink(Base):
    __tablename__ = "invite_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    joins: Mapped[int] = mapped_column(Integer, default=0)
    leaves: Mapped[int] = mapped_column(Integer, default=0)


class MemberEvent(Base):
    __tablename__ = "member_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    user_hash: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(10))  # join | leave
    invite_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("invite_links.id", ondelete="SET NULL"), nullable=True
    )


class QALog(Base):
    __tablename__ = "qa_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_hash: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # dm | comments | channel_dm
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_hash: Mapped[str] = mapped_column(String(64), index=True)
    excerpt: Mapped[str] = mapped_column(String(300))
    label: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    role: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(50), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
