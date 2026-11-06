"""Telegram sozlamalarini tekshirish (faqat o'qish — hech qanday xabar yubormaydi).

Bot tokeni, privacy rejimi, kanal/test kanal/izohlar guruhidagi admin huquqlarini ko'rsatadi.
Ishlatish:  python scripts/check_telegram.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot

from app.config import get_settings

CHANNEL_RIGHTS = (
    "can_post_messages",
    "can_edit_messages",
    "can_delete_messages",
    "can_invite_users",
    "can_manage_direct_messages",
    "can_promote_members",
)
GROUP_RIGHTS = ("can_delete_messages", "can_restrict_members", "can_invite_users", "can_promote_members")


async def describe_chat(bot: Bot, label: str, chat_id: int | None, rights: tuple[str, ...]) -> list[str]:
    if chat_id is None:
        return [f"— {label}: sozlanmagan"]
    problems: list[str] = []
    try:
        chat = await bot.get_chat(chat_id)
        member = await bot.get_chat_member(chat_id, bot.id)
    except Exception as exc:
        print(f"XATO {label} ({chat_id}): {exc}")
        return [f"{label}: bot chatni koʻra olmayapti — botni u yerga admin qiling"]
    status = getattr(member.status, "value", member.status)
    print(f"OK   {label}: «{chat.title}» ({chat.type}), bot holati: {status}")
    linked = getattr(chat, "linked_chat_id", None)
    if linked:
        print(f"     bogʻlangan izohlar guruhi: {linked}")
    for right in rights:
        value = getattr(member, right, None)
        if value is None:
            continue
        mark = "✓" if value else "✗"
        print(f"     {mark} {right}")
        if right == "can_promote_members" and value:
            problems.append(f"{label}: botga 'yangi admin qoʻshish' huquqi berilmasin (SPEC 12)")
        elif right != "can_promote_members" and right != "can_manage_direct_messages" and not value:
            problems.append(f"{label}: {right} huquqi yoqilmagan")
    if status != "administrator":
        problems.append(f"{label}: bot administrator emas")
    return problems


async def main() -> int:
    s = get_settings()
    if not s.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN .env da yoʻq")
        return 1
    bot = Bot(token=s.telegram_bot_token.get_secret_value())
    problems: list[str] = []
    try:
        me = await bot.me()
        print(f"OK   Bot: @{me.username} (id {me.id})")
        if not me.can_read_all_group_messages:
            problems.append("BotFather → /setprivacy → Disable qiling (izohlar guruhini oʻqish uchun)")
        print(f"     privacy oʻchirilgan (guruh xabarlarini oʻqiydi): {bool(me.can_read_all_group_messages)}")
        problems += await describe_chat(bot, "Haqiqiy kanal (CHANNEL_ID)", s.channel_id, CHANNEL_RIGHTS)
        problems += await describe_chat(
            bot, "Test kanal (TEST_CHANNEL_ID)", s.test_channel_id, CHANNEL_RIGHTS
        )
        problems += await describe_chat(
            bot, "Izohlar guruhi (DISCUSSION_GROUP_ID)", s.discussion_group_id, GROUP_RIGHTS
        )
        if s.test_group_id:
            problems += await describe_chat(bot, "Test guruh (TEST_GROUP_ID)", s.test_group_id, GROUP_RIGHTS)
        if not s.admin_ids:
            problems.append("ADMIN_IDS boʻsh — botga /id yozib, oʻz ID raqamingizni oling")
    finally:
        await bot.session.close()
    print("\nMuammolar:" if problems else "\n✅ Telegram sozlamalari joyida.")
    for p in problems:
        print(f" • {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
