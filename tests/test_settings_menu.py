"""/settings: checkbox menyu — kuniga nechta post, soat nechida, qaysi turkumlar, haftalik soʻrovnoma/test."""

from app.bot.setup import build_dispatcher
from app.scheduler.setup import setup_scheduler
from tests.tg import button_data, callback_answers, callback_update, last_markup, make_bot, msg_update

ADMIN, STRANGER = 1, 999


def dispatcher(ctx):
    return build_dispatcher(ctx), make_bot()


async def press(dp, bot, needle: str, user: int = ADMIN) -> None:
    buttons = button_data(last_markup(bot))
    matches = [data for text, data in buttons.items() if needle in text]
    assert len(matches) == 1, f"{needle!r}: {list(buttons)}"
    await dp.feed_update(bot, callback_update(matches[0], user))


def labels(bot) -> list[str]:
    return list(button_data(last_markup(bot)))


async def test_settings_toggle_time_and_category(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "Vaqtlar")
    assert "✅ 08:30" in labels(bot) and "▫️ 10:00" in labels(bot)
    await press(dp, bot, "10:00")
    assert await ctx.runtime.get("slot_times") == ["08:30", "10:00", "13:00", "19:30"]
    assert "✅ 10:00" in labels(bot)  # menyu oʻsha joyda yangilanadi
    await press(dp, bot, "13:00")
    assert await ctx.runtime.get("slot_times") == ["08:30", "10:00", "19:30"]

    await press(dp, bot, "Orqaga")
    await press(dp, bot, "Turkumlar")
    await press(dp, bot, "saytlar")
    assert "sayt" not in await ctx.runtime.get("categories")
    assert any(t.startswith("▫️") and "saytlar" in t for t in labels(bot))
    await press(dp, bot, "saytlar")
    assert "sayt" in await ctx.runtime.get("categories")


async def test_custom_time_from_set_is_shown_and_removable(ctx) -> None:
    await ctx.runtime.set("slot_times", ["08:15", "13:00"])
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "Vaqtlar")
    assert "✅ 08:15" in labels(bot)
    await press(dp, bot, "08:15")
    assert await ctx.runtime.get("slot_times") == ["13:00"]


async def test_last_category_cannot_be_removed(ctx) -> None:
    await ctx.runtime.set("categories", ["ai"])
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "Turkumlar")
    await press(dp, bot, "Sunʼiy intellekt")
    assert await ctx.runtime.get("categories") == ["ai"]
    assert any("Kamida bitta" in a for a in callback_answers(bot))


async def test_max_posts_per_day(ctx) -> None:
    await ctx.runtime.set(
        "slot_times", ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]
    )
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "Vaqtlar")
    await press(dp, bot, "16:00")
    assert len(await ctx.runtime.get("slot_times")) == 8
    assert any("8 ta" in a for a in callback_answers(bot))


async def test_poll_and_quiz_counters(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "📊 +")
    assert await ctx.runtime.get("polls_per_week") == 3
    assert any("3/hafta" in t for t in labels(bot))
    for _ in range(3):
        await press(dp, bot, "❓ −")
    assert await ctx.runtime.get("quizzes_per_week") == 0  # 0 dan pastga tushmaydi
    await ctx.runtime.set("polls_per_week", 7)
    await press(dp, bot, "📊 +")
    assert await ctx.runtime.get("polls_per_week") == 7


async def test_time_toggle_reschedules_slot_jobs(ctx) -> None:
    scheduler = await setup_scheduler(ctx, persistent=False)
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "Vaqtlar")
    await press(dp, bot, "10:00")
    await press(dp, bot, "13:00")
    ids = {j.id for j in scheduler.get_jobs() if j.id.startswith("slot_")}
    assert ids == {"slot_0830", "slot_1000", "slot_1930"}


async def test_settings_buttons_ignored_for_non_admin(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    await press(dp, bot, "Vaqtlar")
    await press(dp, bot, "10:00", user=STRANGER)
    assert await ctx.runtime.get("slot_times") == ["08:30", "13:00", "19:30"]


async def test_menu_button_opens_interactive_settings(ctx) -> None:
    from app.bot.keyboards import MenuCB

    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, callback_update(MenuCB(action="settings").pack(), ADMIN))
    assert any("Vaqtlar" in t for t in labels(bot))
