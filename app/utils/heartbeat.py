"""Heartbeat fayli: Docker healthcheck uchun."""

from __future__ import annotations

import time
from pathlib import Path


def touch_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(time.time())), encoding="utf-8")


def heartbeat_age(path: Path, now: float | None = None) -> float:
    """Oxirgi yangilanishdan beri o'tgan soniyalar (fayl bo'lmasa — cheksiz)."""
    try:
        return (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return float("inf")
