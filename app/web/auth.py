"""Telegram WebApp `initData` imzosini tekshirish (faqat adminlar)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram.utils.web_app import safe_parse_webapp_init_data

MAX_AGE = timedelta(hours=24)


def verify_init_data(token: str, init_data: str, *, now: datetime | None = None) -> int | None:
    """Imzo toʻgʻri va 24 soatdan eski boʻlmasa — foydalanuvchi ID si, aks holda None."""
    if not token or not init_data:
        return None
    try:
        data = safe_parse_webapp_init_data(token, init_data)
    except ValueError:
        return None
    auth_date = data.auth_date if data.auth_date.tzinfo else data.auth_date.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) - auth_date > MAX_AGE:
        return None
    return data.user.id if data.user else None
