"""Vaqtinchalik tarmoq xatolari (internet, DNS, MongoDB, Telegram) — bular dastur xatosi emas."""

from __future__ import annotations

import asyncio

import httpx
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from pymongo.errors import AutoReconnect, NetworkTimeout, ServerSelectionTimeoutError

try:  # aiohttp aiogram bilan birga oʻrnatiladi
    from aiohttp import ClientConnectionError
except ImportError:  # pragma: no cover
    ClientConnectionError = OSError  # type: ignore[misc,assignment]

TRANSIENT: tuple[type[BaseException], ...] = (
    AutoReconnect,  # ConnectionFailure ning tarmoq qismi: getaddrinfo, pool paused, reset
    NetworkTimeout,
    ServerSelectionTimeoutError,
    httpx.TransportError,
    TelegramNetworkError,
    TelegramServerError,
    TelegramRetryAfter,
    ClientConnectionError,
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)


def is_transient(exc: BaseException) -> bool:
    """Internet/DNS/server vaqtincha ishlamayapti — oʻzi tiklanadi (zanjirdagi sabab ham tekshiriladi)."""
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 5:
        if isinstance(current, TRANSIENT):
            return True
        if isinstance(current, OSError) and current.errno in (11001, 11002, -2, -3, 101, 110, 111, 113):
            return True  # DNS topilmadi, tarmoq yoʻq, ulanish rad etildi
        current = current.__cause__ or current.__context__
        seen += 1
    return False
