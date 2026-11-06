"""Inline klaviaturalar va callback ma'lumotlari."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.timeutil import to_tz, utcnow


class MenuCB(CallbackData, prefix="menu"):
    action: str


class ApprovalCB(CallbackData, prefix="ap"):
    action: str  # pub | sched | edit | rewrite | img | rej
    post_id: int


class ManualCB(CallbackData, prefix="mp"):
    action: str  # now | at | other | cancel
    post_id: int
    ts: int = 0  # "at" uchun: UTC unix vaqt


class SettingsCB(CallbackData, prefix="st"):
    action: str  # view | t (vaqt) | c (turkum) | pl | qz | all | noop
    value: str = ""


class ModCB(CallbackData, prefix="mod"):
    action: str  # ban | skip
    chat_id: int
    user_id: int


class SourceCB(CallbackData, prefix="src"):
    action: str  # toggle
    source_id: int


MENU_ITEMS: list[tuple[str, str]] = [
    ("📊 Holat", "status"),
    ("🗂 Navbat", "queue"),
    ("📈 Statistika", "stats"),
    ("🚀 O'sish", "growth"),
    ("💰 Budjet", "budget"),
    ("📡 Manbalar", "sources"),
    ("⚙️ Sozlamalar", "settings"),
    ("🧾 Xatolar", "logs"),
]


def main_menu() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(MENU_ITEMS), 2):
        rows.append(
            [
                InlineKeyboardButton(text=title, callback_data=MenuCB(action=action).pack())
                for title, action in MENU_ITEMS[i : i + 2]
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def approval_keyboard(post_id: int) -> InlineKeyboardMarkup:
    def b(text: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=text, callback_data=ApprovalCB(action=action, post_id=post_id).pack()
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [b("✅ Chiqarish", "pub"), b("🕒 Vaqtga qo'yish", "sched")],
            [b("✏️ Tahrirlash", "edit"), b("🔄 Qayta yozish", "rewrite")],
            [b("🖼 Boshqa rasm", "img"), b("❌ Rad etish", "rej")],
        ]
    )


def _day_label(when: datetime, tz: str) -> str:
    local, today = to_tz(when, tz), to_tz(utcnow(), tz).date()
    days = (local.date() - today).days
    day = {0: "Bugun", 1: "Ertaga"}.get(days, local.strftime("%d.%m"))
    return f"{day} {local:%H:%M}"


def manual_keyboard(post_id: int, slots: Sequence[datetime], tz: str) -> InlineKeyboardMarkup:
    """Qoʻlda post: hozir / keyingi boʻsh slotlar / boshqa vaqt / bekor."""

    def b(text: str, action: str, ts: int = 0) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=text, callback_data=ManualCB(action=action, post_id=post_id, ts=ts).pack()
        )

    slot_buttons = [b(f"🕒 {_day_label(t, tz)}", "at", int(t.timestamp())) for t in slots]
    rows = [[b("🚀 Hozir chiqarish", "now")]]
    rows += [slot_buttons[i : i + 2] for i in range(0, len(slot_buttons), 2)]
    rows.append([b("⏰ Boshqa vaqt", "other"), b("❌ Bekor qilish", "cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ban_keyboard(chat_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 Ban", callback_data=ModCB(action="ban", chat_id=chat_id, user_id=user_id).pack()
                ),
                InlineKeyboardButton(
                    text="Kerak emas",
                    callback_data=ModCB(action="skip", chat_id=chat_id, user_id=user_id).pack(),
                ),
            ]
        ]
    )
