"""SQLite backup: har kuni 03:00, 7 kun saqlanadi; dushanba kuni nusxa adminga yuboriladi."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

KEEP_DAYS = 7
SEND_WEEKDAY = 0  # dushanba
MAX_SEND_BYTES = 45 * 1024 * 1024


def _copy(src: Path, dest: Path) -> None:
    source = sqlite3.connect(src)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def prune_backups(folder: Path, keep_days: int = KEEP_DAYS, now: float | None = None) -> int:
    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    removed = 0
    for f in folder.glob("bot-*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


async def backup_sqlite(
    db_path: Path, backup_dir: Path, *, keep_days: int = KEEP_DAYS, now: datetime | None = None
) -> Path:
    await asyncio.to_thread(backup_dir.mkdir, parents=True, exist_ok=True)
    stamp = (now or utcnow()).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"bot-{stamp}.db"
    await asyncio.to_thread(_copy, db_path, dest)
    await asyncio.to_thread(prune_backups, backup_dir, keep_days)
    return dest


class BackupService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    def _db_path(self) -> Path | None:
        url = self.ctx.settings.database_url
        if not url.startswith("sqlite") or ":memory:" in url:
            return None
        return Path(url.split("///", 1)[-1])

    async def run(self) -> Path | None:
        db = self._db_path()
        if db is None or not db.exists():
            return None
        now = self.clock()
        dest = await backup_sqlite(db, self.ctx.settings.data_path / "backups", now=now)
        logger.info("Backup tayyor: {}", dest)
        if (
            to_tz(now, self.ctx.settings.tz).weekday() == SEND_WEEKDAY
            and dest.stat().st_size <= MAX_SEND_BYTES
        ):
            data = await asyncio.to_thread(dest.read_bytes)
            for admin_id in self.ctx.settings.admin_ids:
                try:
                    await self.ctx.sender.send_document(
                        admin_id, data, dest.name, "🗄 Haftalik backup (bot.db)"
                    )
                except Exception as exc:
                    logger.warning("Backup adminga yuborilmadi: {}", exc)
        return dest
