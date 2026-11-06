from app.bot.setup import build_dispatcher
from tests.tg import make_bot, msg_update, sent_texts

ADMIN = 1
STRANGER = 999


async def test_non_admin_cannot_use_admin_command(ctx) -> None:
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/status", STRANGER))
    texts = sent_texts(bot)
    assert texts, "foydalanuvchiga javob berilishi kerak"
    joined = "\n".join(texts)
    assert "Rejim" not in joined and "$" not in joined


async def test_status_for_admin_contains_mode_spend_and_target(ctx) -> None:
    await ctx.repo.record_usage(role="editor", provider="openai", model="gpt-6-sol", cost_usd=0.42)
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/status", ADMIN))
    text = "\n".join(sent_texts(bot))
    assert "Rejim" in text and "semi_auto" in text
    assert "$0.42" in text
    assert "DRY_RUN" in text and "-1001" in text


async def test_mode_command_changes_runtime_mode(ctx) -> None:
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/mode auto", ADMIN))
    assert await ctx.runtime.publish_mode() == "auto"
    await dp.feed_update(bot, msg_update("/mode yomon", ADMIN))
    assert await ctx.runtime.publish_mode() == "auto"


async def test_mode_command_ignored_for_stranger(ctx) -> None:
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/mode auto", STRANGER))
    assert await ctx.runtime.publish_mode() == "semi_auto"


async def test_pause_and_resume(ctx) -> None:
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/pause", ADMIN))
    assert await ctx.runtime.paused() is True
    await dp.feed_update(bot, msg_update("/resume", ADMIN))
    assert await ctx.runtime.paused() is False


async def test_id_command_shows_chat_id_for_admin(ctx) -> None:
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/id", ADMIN, chat_id=-100555, chat_type="supergroup"))
    assert any("-100555" in t for t in sent_texts(bot))


async def test_budget_command_lists_roles(ctx) -> None:
    await ctx.repo.record_usage(role="writer", provider="anthropic", model="claude-x", cost_usd=0.1)
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/budget", ADMIN))
    text = "\n".join(sent_texts(bot))
    assert "writer" in text and "anthropic" in text


async def test_logs_command_shows_recent_errors(ctx) -> None:
    await ctx.repo.audit("system", "error", message="RSS xatosi: timeout")
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/logs", ADMIN))
    assert any("RSS xatosi" in t for t in sent_texts(bot))
