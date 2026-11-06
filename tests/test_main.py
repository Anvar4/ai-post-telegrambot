from pathlib import Path

import pytest

from app.main import build_context
from tests.conftest import make_settings
from tests.mongo_fake import FakeDatabase


async def test_build_context_wires_router_indexes_and_salt(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        telegram_bot_token="42:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123",
        openai_api_key="sk-test-abcdefghijklmnop",
        hash_salt=None,
    )
    db = FakeDatabase()
    ctx, bot, client = await build_context(settings, db=db)
    try:
        assert client is None  # tashqi baza berilganda ulanish ochilmaydi
        assert ctx.router.describe()["editor"] == "openai/gpt-6-sol"
        assert ctx.router.describe()["writer"] == "—"
        assert len(ctx.salt) == 32  # bo'sh HASH_SALT -> yaratilgan va bazada saqlangan
        assert await ctx.repo.get_setting("hash_salt") == ctx.salt
        assert any("LLM_MAIN_PROVIDER" in p for p in ctx.services["config_problems"])
        assert (tmp_path / "images").is_dir()
        assert await ctx.repo.sources.count() > 0  # boshlang'ich manbalar qo'shildi
        assert "articles" in await db.list_collection_names()  # indekslar yaratildi
    finally:
        if ctx.http is not None:
            await ctx.http.aclose()
        await bot.session.close()


async def test_build_context_requires_mongodb_uri(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, telegram_bot_token="42:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123")
    with pytest.raises(ValueError, match="MONGODB_URI"):
        await build_context(settings)
