"""Async engine, sessiya fabrikasi va migratsiyalar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base

ROOT = Path(__file__).resolve().parents[2]


def create_engine(url: str) -> AsyncEngine:
    kwargs: dict[str, Any] = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        else:
            db_path = url.split("///", 1)[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url, **kwargs)
    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in url:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    """Faqat testlar uchun: jadvallarni to'g'ridan-to'g'ri yaratish."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def run_migrations(url: str) -> None:
    """`alembic upgrade head` (sinxron; event loop ichidan `asyncio.to_thread` bilan chaqiring)."""
    from alembic import command
    from alembic.config import Config

    if url.startswith("sqlite") and ":memory:" not in url:
        Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
