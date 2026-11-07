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


async def test_start_opens_panel_button_when_webapp_configured(ctx, tmp_path) -> None:
    from tests.conftest import make_settings
    from tests.tg import last_markup

    ctx.settings = make_settings(tmp_path, webapp_url="https://1-2-3-4.sslip.io")
    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/start", ADMIN))
    buttons = [b for row in last_markup(bot).inline_keyboard for b in row]
    panel = [b for b in buttons if b.web_app is not None]
    assert panel and panel[0].web_app.url == "https://1-2-3-4.sslip.io"
    text = "\n".join(sent_texts(bot))
    assert "/post" not in text  # uzun buyruqlar roʻyxati endi alohida tugmada


async def test_start_without_webapp_has_menu_and_help_button(ctx) -> None:
    from app.bot.keyboards import MenuCB
    from tests.tg import callback_update, last_markup

    dp = build_dispatcher(ctx)
    bot = make_bot()
    await dp.feed_update(bot, msg_update("/start", ADMIN))
    texts = [b.text for row in last_markup(bot).inline_keyboard for b in row]
    assert any("Buyruqlar" in t for t in texts)
    await dp.feed_update(bot, callback_update(MenuCB(action="help").pack(), ADMIN))
    assert "/post" in "\n".join(sent_texts(bot))


async def test_panel_menu_button_set_for_admins(ctx, tmp_path) -> None:
    from aiogram.methods import SetChatMenuButton

    from app.web.server import setup_panel_button
    from tests.conftest import make_settings

    settings = make_settings(tmp_path, admin_ids=[1, 2], webapp_url="https://1-2-3-4.sslip.io")
    bot = make_bot()
    assert await setup_panel_button(bot, settings) == 2
    calls = [m for m in bot.session.requests if isinstance(m, SetChatMenuButton)]
    assert sorted(c.chat_id for c in calls) == [1, 2]
    assert calls[0].menu_button.web_app.url == "https://1-2-3-4.sslip.io"
    assert await setup_panel_button(bot, make_settings(tmp_path)) == 0  # URL yoʻq — tugma qoʻyilmaydi
