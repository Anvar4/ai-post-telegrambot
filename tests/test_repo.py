import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.db.models import LLMUsage, ModerationEvent, Post, QALog, Story
from app.pipeline.state import PostKind, PostStatus

TASHKENT = ZoneInfo("Asia/Tashkent")


async def test_settings_roundtrip(repo) -> None:
    assert await repo.get_setting("schedule", {"x": 0}) == {"x": 0}
    await repo.set_setting("schedule", {"slots": ["08:30"]})
    assert await repo.get_setting("schedule") == {"slots": ["08:30"]}
    await repo.set_setting("schedule", {"slots": ["09:00"]})
    assert await repo.get_setting("schedule") == {"slots": ["09:00"]}


async def test_ids_autoincrement_per_collection(repo) -> None:
    a = await repo.posts.insert(Post(kind=PostKind.NEWS, text_html="a"))
    b = await repo.posts.insert(Post(kind=PostKind.NEWS, text_html="b"))
    s = await repo.stories.insert(Story(title="s"))
    assert (a.id, b.id, s.id) == (1, 2, 1)
    assert (await repo.posts.get(2)).text_html == "b"


async def test_datetimes_roundtrip_as_aware_utc(repo) -> None:
    ts = datetime(2026, 11, 6, 10, 0, tzinfo=TASHKENT)
    await repo.llm_usage.insert(LLMUsage(ts=ts, role="writer", provider="openai", model="m", cost_usd=0.1))
    row = (await repo.llm_usage.find({}))[0]
    assert row.ts.tzinfo is not None
    assert row.ts == datetime(2026, 11, 6, 5, 0, tzinfo=UTC)


async def test_filter_with_aware_datetime(repo) -> None:
    base = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    for h in (1, 5, 9):
        await repo.stories.insert(Story(title=f"s{h}", first_seen=base - timedelta(hours=h)))
    since = base.astimezone(TASHKENT) - timedelta(hours=6)
    found = await repo.stories.find({"first_seen": {"$gte": since}}, sort=[("first_seen", -1)])
    assert [s.title for s in found] == ["s1", "s5"]


async def test_save_and_update_fields(repo) -> None:
    post = await repo.posts.insert(Post(kind=PostKind.NEWS, text_html="x", extra={"a": 1}))
    post.text_html = "y"
    post.extra = {**post.extra, "b": 2}
    await repo.posts.save(post)
    await repo.posts.update(post.id, {"title_short": "T"})
    got = await repo.posts.get(post.id)
    assert (got.text_html, got.extra, got.title_short) == ("y", {"a": 1, "b": 2}, "T")


async def test_cas_only_one_wins(repo) -> None:
    post = await repo.posts.insert(Post(kind=PostKind.NEWS, status=PostStatus.SCHEDULED, text_html="x"))
    results = await asyncio.gather(
        *(
            repo.posts.cas(post.id, {"status": PostStatus.SCHEDULED}, {"status": PostStatus.PUBLISHING})
            for _ in range(5)
        )
    )
    assert results.count(True) == 1
    assert (await repo.posts.get(post.id)).status == PostStatus.PUBLISHING


async def test_spent_today_tashkent_day(repo) -> None:
    await repo.llm_usage.insert(
        LLMUsage(
            ts=datetime(2026, 11, 5, 19, 30, tzinfo=UTC), role="w", provider="p", model="m", cost_usd=1.0
        )
    )
    await repo.llm_usage.insert(
        LLMUsage(
            ts=datetime(2026, 11, 5, 18, 30, tzinfo=UTC), role="w", provider="p", model="m", cost_usd=5.0
        )
    )
    now = datetime(2026, 11, 6, 10, 0, tzinfo=TASHKENT)
    assert abs(await repo.spent_today(now) - 1.0) < 1e-9


async def test_cleanup_old_qa_and_moderation(repo) -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    old, recent = now - timedelta(days=91), now - timedelta(days=1)
    await repo.qa_logs.insert(QALog(user_hash="u", channel="dm", question="q", answer="a", ts=old))
    await repo.qa_logs.insert(QALog(user_hash="u", channel="dm", question="q2", answer="a", ts=recent))
    await repo.moderation_events.insert(
        ModerationEvent(
            user_hash="u", excerpt="x", label="spam", action="delete", ts=now - timedelta(days=100)
        )
    )
    await repo.moderation_events.insert(
        ModerationEvent(user_hash="u", excerpt="y", label="spam", action="delete", ts=now)
    )
    assert await repo.cleanup_old(now, days=90) == 2
    assert [q.question for q in await repo.qa_logs.find({})] == ["q2"]
    assert [m.excerpt for m in await repo.moderation_events.find({})] == ["y"]


async def test_usage_breakdown_groups_by_role(repo) -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    for role, cost, ok in (("writer", 0.5, True), ("writer", 0.25, False), ("editor", 1.0, True)):
        await repo.llm_usage.insert(
            LLMUsage(ts=now, role=role, provider="openai", model="m", cost_usd=cost, ok=ok)
        )
    rows = await repo.usage_breakdown(now, days=1)
    by_role = {(r["role"], r["provider"]): r for r in rows}
    assert by_role[("writer", "openai")]["cost_usd"] == 0.75
    assert by_role[("writer", "openai")]["errors"] == 1
    assert by_role[("editor", "openai")]["calls"] == 1
    assert rows[0]["role"] == "editor"  # eng qimmati birinchi


async def test_audit_and_recent_errors(repo) -> None:
    await repo.audit("system", "error", message="boom", key="x")
    await repo.audit("admin", "mode", value="auto")
    errors = await repo.recent_errors(limit=5)
    assert len(errors) == 1 and errors[0]["message"] == "boom"
    assert await repo.count_errors(datetime(2000, 1, 1, tzinfo=UTC)) == 1


async def test_posts_by_status_ordered(repo) -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    await repo.posts.insert(
        Post(kind="news", status=PostStatus.SCHEDULED, scheduled_at=now + timedelta(hours=2))
    )
    await repo.posts.insert(
        Post(kind="news", status=PostStatus.SCHEDULED, scheduled_at=now + timedelta(hours=1))
    )
    await repo.posts.insert(Post(kind="news", status=PostStatus.PUBLISHED))
    rows = await repo.posts_by_status(PostStatus.SCHEDULED)
    assert [p.id for p in rows] == [2, 1]


async def test_ensure_indexes_unique_url_hash(db) -> None:
    from app.db.mongo import ensure_indexes

    await ensure_indexes(db)
    await ensure_indexes(db)  # takror chaqirish xavfsiz
    await db["articles"].insert_one({"_id": 1, "url_hash": "h"})
    try:
        await db["articles"].insert_one({"_id": 2, "url_hash": "h"})
    except Exception as exc:
        assert "duplicate" in str(exc).lower() or "E11000" in str(exc)
    else:
        raise AssertionError("url_hash unique bo'lishi kerak")


async def test_next_ids_allocates_contiguous_block(repo) -> None:
    assert await repo.next_ids("stories", 3) == [1, 2, 3]
    assert await repo.next_id("stories") == 4
    assert await repo.next_ids("stories", 0) == []


async def test_insert_many_assigns_ids_and_skips_duplicates(repo, db) -> None:
    from app.db.models import Article
    from app.db.mongo import ensure_indexes

    await ensure_indexes(db)
    await repo.articles.insert(Article(url="u0", url_hash="h0", title="t"))
    batch = [Article(url=f"u{i}", url_hash=f"h{i}", title="t") for i in range(3)]  # h0 takror
    assert await repo.articles.insert_many(batch) == 2
    assert await repo.articles.count() == 3
    assert all(a.id is not None for a in batch)
    assert await repo.articles.insert_many([]) == 0
