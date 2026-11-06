"""Xeshlash va sirlarni maskalash."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"),  # Telegram bot token
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # OpenAI / DeepSeek
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),  # Google
    re.compile(r"r8_[A-Za-z0-9]{20,}"),  # Replicate
    re.compile(r"(?i)(authorization:\s*(?:bearer|key)\s+)[^\s'\"]+"),
]

_registered: set[str] = set()


def register_secret(value: str | None) -> None:
    """Aniq sir qiymatini maskalash ro'yxatiga qo'shish (masalan .env dagi kalitlar)."""
    if value and len(value) >= 6:
        _registered.add(value)


def mask_secrets(text: str, extra: Iterable[str] = ()) -> str:
    for secret in (*_registered, *extra):
        if secret:
            text = text.replace(secret, "***")
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "***", text)
        else:
            text = pattern.sub("***", text)
    return text


def hash_user_id(user_id: int, salt: str) -> str:
    """Obunachi ID sini tuzli HMAC bilan xeshlash (qaytarib bo'lmaydi)."""
    return hmac.new(salt.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()[:32]
