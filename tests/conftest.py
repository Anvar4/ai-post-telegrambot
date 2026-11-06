from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.ai.router import AIRouter
from app.config import Settings
from app.context import AppContext
from app.db.repo import Repo
from app.db.session import create_all, create_engine, make_sessionmaker
from app.utils.runtime import Runtime
from tests.fakes import FakeNotifier, FakeSender


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_engine("sqlite+aiosqlite:///:memory:")
    await create_all(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest_asyncio.fixture
async def repo(sessionmaker: async_sessionmaker[AsyncSession]) -> Repo:
    return Repo(sessionmaker, tz="Asia/Tashkent")


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "admin_ids": [1],
        "test_channel_id": -1001,
        "channel_id": -1002,
        "channel_username": "@it_dunyosi",
        "dry_run": True,
        "publish_mode": "semi_auto",
        "data_dir": tmp_path,
        "hash_salt": "test-salt",
        "discussion_group_id": -1003,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def ctx(repo: Repo, tmp_path: Path) -> AppContext:
    settings = make_settings(tmp_path)
    sender = FakeSender()
    notifier = FakeNotifier()
    router = AIRouter({"writer": None, "editor": None, "fast": None}, repo=repo, sleep=_no_sleep)
    return AppContext(
        settings=settings,
        repo=repo,
        router=router,
        sender=sender,
        notifier=notifier,  # type: ignore[arg-type]
        runtime=Runtime(repo, settings),
        salt="test-salt",
    )


async def _no_sleep(_: float) -> None:
    return None


def use_llm(
    ctx: AppContext,
    *,
    writer: Any = None,
    editor: Any = None,
    fast: Any = None,
    image: Any = None,
    budget: Any = None,
) -> AIRouter:
    """Kontekstga soxta AI mijozlarini ulash."""
    ctx.router = AIRouter(
        {"writer": writer, "editor": editor, "fast": fast},
        image=image,
        repo=ctx.repo,
        budget=budget,
        sleep=_no_sleep,
    )
    return ctx.router
