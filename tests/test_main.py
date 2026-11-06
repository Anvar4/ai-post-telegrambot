from pathlib import Path

from sqlalchemy import inspect

from app.main import build_context
from tests.conftest import make_settings


async def test_build_context_runs_migrations_and_wires_router(tmp_path: Path) -> None:
    db = tmp_path / "bot.db"
    settings = make_settings(
        tmp_path,
        database_url=f"sqlite+aiosqlite:///{db.as_posix()}",
        telegram_bot_token="42:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123",
        openai_api_key="sk-test-abcdefghijklmnop",
        hash_salt=None,
    )
    ctx, bot, engine = await build_context(settings)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert {"posts", "stories", "llm_usage"} <= tables
        assert ctx.router.describe()["editor"] == "openai/gpt-6-sol"
        assert ctx.router.describe()["writer"] == "—"
        assert len(ctx.salt) == 32  # bo'sh HASH_SALT -> yaratilgan va DB da saqlangan
        assert await ctx.repo.get_setting("hash_salt") == ctx.salt
        assert any("LLM_MAIN_PROVIDER" in p for p in ctx.services["config_problems"])
        assert (tmp_path / "images").is_dir()
    finally:
        if ctx.http is not None:
            await ctx.http.aclose()
        await bot.session.close()
        await engine.dispose()
