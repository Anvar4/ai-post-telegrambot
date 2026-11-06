"""Inline klaviaturalar va callback ma'lumotlari."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class MenuCB(CallbackData, prefix="menu"):
    action: str


class ApprovalCB(CallbackData, prefix="ap"):
    action: str  # pub | sched | edit | rewrite | img | rej
    post_id: int


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
