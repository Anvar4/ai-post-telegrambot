"""/settings: checkbox menyu — kuniga nechta post va soat nechida, turkumlar, haftalik soʻrovnoma/test."""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.handlers.admin import MENU_HANDLERS
from app.bot.handlers.admin_content import reschedule, settings_text
from app.bot.keyboards import SettingsCB
from app.bot.middlewares import AdminFilter
from app.content.schedule import (
    ALL_CATEGORIES,
    CATEGORY_LABELS,
    MAX_SLOTS_PER_DAY,
    TIME_CHOICES,
    normalize_times,
)
from app.context import AppContext
from app.pipeline.image import IMAGE_MODES

WEEKLY_MAX = 7
IMAGE_MODE_UZ = {
    "search_then_ask": "internetdan (bepul)",
    "none": "rasmsiz",
}


def _b(text: str, action: str, value: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=SettingsCB(action=action, value=value).pack())


async def main_view(ctx: AppContext) -> tuple[str, InlineKeyboardMarkup]:
    rt = ctx.runtime
    times = list(await rt.get("slot_times"))
    cats = list(await rt.get("categories"))
    polls, quizzes = int(await rt.get("polls_per_week")), int(await rt.get("quizzes_per_week"))
    image_mode = str(await rt.get("image_mode"))
    share = bool(await rt.get("share_button"))
    names = ", ".join(CATEGORY_LABELS[c].split(" ", 1)[1] for c in cats if c in CATEGORY_LABELS)
    text = "\n".join(
        [
            "⚙️ <b>Sozlamalar</b>",
            "",
            f"🕒 Kuniga <b>{len(times)}</b> ta post: {', '.join(times) or '— (faqat shoshilinch va qoʻlda)'}",
            f"🗂 Turkumlar: {names}",
            f"📊 Soʻrovnoma: haftasiga <b>{polls}</b> · ❓ Test: haftasiga <b>{quizzes}</b>",
            f"🖼 Rasm: {IMAGE_MODE_UZ.get(image_mode, image_mode)}",
            f"📤 Ulashish tugmasi: {'yoqilgan' if share else 'oʻchirilgan'}",
            "",
            "Tugmalar bilan oʻzgartiring. Matn bilan: <code>/set kalit qiymat</code>.",
        ]
    )
    kb = [
        [_b(f"🕒 Vaqtlar ({len(times)})", "view", "times"), _b(f"🗂 Turkumlar ({len(cats)})", "view", "cats")],
        [_b("📊 −", "pl", "-"), _b(f"📊 Soʻrovnoma: {polls}/hafta", "noop"), _b("📊 +", "pl", "+")],
        [_b("❓ −", "qz", "-"), _b(f"❓ Test: {quizzes}/hafta", "noop"), _b("❓ +", "qz", "+")],
        [_b(f"🖼 Rasm: {IMAGE_MODE_UZ.get(image_mode, image_mode)}", "img")],
        [_b(f"📤 Ulashish tugmasi: {'✅' if share else '▫️'}", "share")],
        [_b("🔧 Boshqa sozlamalar", "all")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=kb)


async def times_view(ctx: AppContext) -> tuple[str, InlineKeyboardMarkup]:
    selected = list(await ctx.runtime.get("slot_times"))
    choices = sorted(set(TIME_CHOICES) | set(selected))
    buttons = [_b(f"{'✅' if t in selected else '▫️'} {t}", "t", t.replace(":", "")) for t in choices]
    rows = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    rows.append([_b("⬅️ Orqaga", "view", "main")])
    text = (
        f"🕒 <b>Post vaqtlari</b> — kuniga {len(selected)} ta (eng koʻpi {MAX_SLOTS_PER_DAY}).\n"
        f"Belgilangan vaqtlarga bot post tayyorlaydi. Roʻyxatda yoʻq vaqt: "
        "<code>/set slot_times 08:15,13:00,19:30</code>"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def cats_view(ctx: AppContext) -> tuple[str, InlineKeyboardMarkup]:
    selected = list(await ctx.runtime.get("categories"))
    rows = [[_b(f"{'✅' if c in selected else '▫️'} {CATEGORY_LABELS[c]}", "c", c)] for c in ALL_CATEGORIES]
    rows.append([_b("⬅️ Orqaga", "view", "main")])
    text = (
        "🗂 <b>Turkumlar</b> — qaysi mavzularda post chiqsin (kamida bittasi).\n"
        "Oʻchirilgan turkum oʻrniga qolganlari ishlatiladi; "
        "kiberxavfsizlik oʻchsa shoshilinch xabarlar ham chiqmaydi."
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


VIEWS = {"main": main_view, "times": times_view, "cats": cats_view}


async def cmd_settings(message: Message, ctx: AppContext) -> None:
    text, kb = await main_view(ctx)
    await message.answer(text, reply_markup=kb)


async def _toggle_time(call: CallbackQuery, ctx: AppContext, value: str) -> bool:
    hhmm = f"{value[:2]}:{value[2:]}"
    times = list(await ctx.runtime.get("slot_times"))
    if hhmm in times:
        times.remove(hhmm)
    elif len(times) >= MAX_SLOTS_PER_DAY:
        await call.answer(f"Kuniga eng koʻpi {MAX_SLOTS_PER_DAY} ta post", show_alert=True)
        return False
    else:
        times.append(hhmm)
    await ctx.runtime.set("slot_times", normalize_times(times))
    await reschedule(ctx)
    return True


async def _toggle_category(call: CallbackQuery, ctx: AppContext, value: str) -> bool:
    cats = list(await ctx.runtime.get("categories"))
    if value in cats:
        if len(cats) == 1:
            await call.answer("Kamida bitta turkum qolishi kerak", show_alert=True)
            return False
        cats.remove(value)
    elif value in ALL_CATEGORIES:
        cats.append(value)
    await ctx.runtime.set("categories", [c for c in ALL_CATEGORIES if c in cats])
    return True


async def _step(call: CallbackQuery, ctx: AppContext, key: str, value: str) -> bool:
    current = int(await ctx.runtime.get(key))
    new = max(0, min(WEEKLY_MAX, current + (1 if value == "+" else -1)))
    if new == current:
        await call.answer(f"Chegara: 0…{WEEKLY_MAX}")
        return False
    await ctx.runtime.set(key, new)
    return True


async def on_settings(call: CallbackQuery, callback_data: SettingsCB, ctx: AppContext) -> None:
    action, value = callback_data.action, callback_data.value
    view = "main"
    if action == "view":
        view = value if value in VIEWS else "main"
    elif action == "t":
        view = "times"
        if not await _toggle_time(call, ctx, value):
            return
    elif action == "c":
        view = "cats"
        if not await _toggle_category(call, ctx, value):
            return
    elif action in ("pl", "qz"):
        if not await _step(call, ctx, "polls_per_week" if action == "pl" else "quizzes_per_week", value):
            return
    elif action == "img":
        current = str(await ctx.runtime.get("image_mode"))
        nxt = (
            IMAGE_MODES[(IMAGE_MODES.index(current) + 1) % len(IMAGE_MODES)]
            if current in IMAGE_MODES
            else IMAGE_MODES[0]
        )
        await ctx.runtime.set("image_mode", nxt)
    elif action == "share":
        await ctx.runtime.set("share_button", not await ctx.runtime.get("share_button"))
    elif action == "all":
        await call.answer()
        if call.message is not None:
            await call.message.answer(await settings_text(ctx))
        return
    else:
        await call.answer()
        return
    text, kb = await VIEWS[view](ctx)
    await call.answer()
    if call.message is not None and isinstance(call.message, Message):
        with contextlib.suppress(Exception):  # matn oʻzgarmagan boʻlsa Telegram xato beradi
            await call.message.edit_text(text, reply_markup=kb)


MENU_HANDLERS["settings"] = main_view


def create_router() -> Router:
    router = Router(name="settings_menu")
    router.message.filter(AdminFilter(), F.chat.type == "private")
    router.callback_query.filter(AdminFilter())
    router.message.register(cmd_settings, Command("settings"))
    router.callback_query.register(on_settings, SettingsCB.filter())
    return router
