from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, select

from app.db.models import LLMUsage, ModerationEvent, QALog
from app.db.session import create_engine, run_migrations

TASHKENT = ZoneInfo("Asia/Tashkent")


async def test_settings_roundtrip(repo) -> None:
    assert await repo.get_setting("schedule", {"x": 0}) == {"x": 0}
    await repo.set_setting("schedule", {"slots": ["08:30"]})
    assert await repo.get_setting("schedule") == {"slots": ["08:30"]}
    await repo.set_setting("schedule", {"slots": ["09:00"]})
    assert await repo.get_setting("schedule") == {"slots": ["09:00"]}


async def test_datetimes_roundtrip_as_aware_utc(sessionmaker) -> None:
    ts = datetime(2026, 11, 6, 10, 0, tzinfo=TASHKENT)
    async with sessionmaker() as s:
        s.add(LLMUsage(ts=ts, role="writer", provider="openai", model="m", cost_usd=0.1, ok=True))
        await s.commit()
    async with sessionmaker() as s:
        row = (await s.execute(select(LLMUsage))).scalar_one()
    assert row.ts.tzinfo is not None
    assert row.ts == datetime(2026, 11, 6, 5, 0, tzinfo=UTC)


async def test_spent_today_tashkent_day(repo, sessionmaker) -> None:
    async with sessionmaker() as s:
        # 00:30 Toshkent, 6-noyabr -> bugungi
        s.add(
            LLMUsage(
                ts=datetime(2026, 11, 5, 19, 30, tzinfo=UTC),
                role="w",
                provider="p",
                model="m",
                cost_usd=1.0,
                ok=True,
            )
        )
        # 23:30 Toshkent, 5-noyabr -> kechagi
        s.add(
            LLMUsage(
                ts=datetime(2026, 11, 5, 18, 30, tzinfo=UTC),
                role="w",
                provider="p",
                model="m",
                cost_usd=5.0,
                ok=True,
            )
        )
        await s.commit()
    now = datetime(2026, 11, 6, 10, 0, tzinfo=TASHKENT)
    assert abs(await repo.spent_today(now) - 1.0) < 1e-9


async def test_cleanup_old_qa_and_moderation(repo, sessionmaker) -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    async with sessionmaker() as s:
        s.add(QALog(user_hash="u", channel="dm", question="q", answer="a", ts=now - timedelta(days=91)))
        s.add(QALog(user_hash="u", channel="dm", question="q2", answer="a", ts=now - timedelta(days=1)))
        s.add(
            ModerationEvent(
                user_hash="u", excerpt="x", label="spam", action="delete", ts=now - timedelta(days=100)
            )
        )
        s.add(ModerationEvent(user_hash="u", excerpt="y", label="spam", action="delete", ts=now))
        await s.commit()
    removed = await repo.cleanup_old(now, days=90)
    assert removed == 2
    async with sessionmaker() as s:
        qs = (await s.execute(select(QALog.question))).scalars().all()
        ms = (await s.execute(select(ModerationEvent.excerpt))).scalars().all()
    assert qs == ["q2"]
    assert ms == ["y"]


async def test_usage_breakdown_groups_by_role(repo, sessionmaker) -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    async with sessionmaker() as s:
        for role, cost in (("writer", 0.5), ("writer", 0.25), ("editor", 1.0)):
            s.add(LLMUsage(ts=now, role=role, provider="openai", model="m", cost_usd=cost, ok=True))
        await s.commit()
    rows = await repo.usage_breakdown(now, days=1)
    by_role = {(r["role"], r["provider"]): r["cost_usd"] for r in rows}
    assert by_role[("writer", "openai")] == 0.75
    assert by_role[("editor", "openai")] == 1.0


async def test_audit_and_recent_errors(repo) -> None:
    await repo.audit("system", "error", message="boom", key="x")
    await repo.audit("admin", "mode", value="auto")
    errors = await repo.recent_errors(limit=5)
    assert len(errors) == 1
    assert errors[0]["message"] == "boom"


def test_migrations_create_all_tables(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url)
    import sqlalchemy as sa

    sync = sa.create_engine(url.replace("+aiosqlite", ""))
    names = set(inspect(sync).get_table_names())
    sync.dispose()
    expected = {
        "sources",
        "articles",
        "stories",
        "posts",
        "polls",
        "post_metrics",
        "subscriber_snapshots",
        "invite_links",
        "member_events",
        "qa_logs",
        "moderation_events",
        "llm_usage",
        "settings",
        "audit_log",
    }
    assert expected <= names
    assert create_engine is not None


def test_migrations_match_models(tmp_path: Path) -> None:
    """Alembic migratsiyalari modellar bilan bir xil sxema yaratadi (yangi maydon unutilmasin)."""
    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.models import Base

    url = f"sqlite+aiosqlite:///{(tmp_path / 'm2.db').as_posix()}"
    run_migrations(url)
    sync = sa.create_engine(url.replace("+aiosqlite", ""))
    with sync.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    sync.dispose()
    assert diff == [], f"Migratsiya modellardan farq qiladi: {diff}"
