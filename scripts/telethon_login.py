"""Telethon sessiyasini bir marta olish (post koʻrishlari va kanal statistikasi uchun).

Ishlatish:  python scripts/telethon_login.py
Oldin .env ga TG_API_ID va TG_API_HASH yozilgan boʻlsin (my.telegram.org → API development tools).
Telefon raqami, Telegram yuborgan kod va (boʻlsa) 2FA parol shu terminalda soʻraladi.
Sessiya .env dagi TG_SESSION ga yoziladi va ekranga chiqarilmaydi — uni hech kimga bermang:
u akkauntingizga toʻliq kirish huquqini beradi.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings

ENV = Path(".env")


def save_session(value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = [line for line in lines if not line.strip().startswith("TG_SESSION=")]
    lines.append(f"TG_SESSION={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    settings, error = load_settings()
    if settings is None:
        print(error)
        return 1
    if not settings.tg_api_id or not settings.tg_api_hash:
        print("❌ .env da TG_API_ID va TG_API_HASH yoʻq. my.telegram.org → API development tools dan oling.")
        return 1
    client = TelegramClient(StringSession(), settings.tg_api_id, settings.tg_api_hash.get_secret_value())
    await client.start(  # type: ignore[misc]
        phone=lambda: input("Telefon raqamingiz (+998…): ").strip(),
        code_callback=lambda: input("Telegram yuborgan kod: ").strip(),
        password=lambda: getpass.getpass("2FA parol (boʻlmasa Enter): "),
    )
    me = await client.get_me()
    session = client.session.save()  # type: ignore[union-attr]
    await client.disconnect()
    save_session(session)
    print(f"✅ Kirildi: {getattr(me, 'first_name', '')}. Sessiya .env dagi TG_SESSION ga yozildi.")
    print("Botni qayta ishga tushiring — koʻrishlar har 30 daqiqada yangilanadi.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
