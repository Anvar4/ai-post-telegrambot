"""MongoDB backup: har kuni 03:00 barcha kolleksiyalar JSONL.gz ga, 7 kun saqlanadi; dushanba — adminga."""

from __future__ import annotations

import asyncio
import gzip
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bson import json_util
from loguru import logger

from app.utils.timeutil import to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

KEEP_DAYS = 7
SEND_WEEKDAY = 0  # dushanba
MAX_SEND_BYTES = 45 * 1024 * 1024
SKIP_COLLECTIONS = frozenset({"apscheduler_jobs"})


def prune_backups(folder: Path, keep_days: int = KEEP_DAYS, now: float | None = None) -> int:
    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    removed = 0
    for f in folder.glob("bot-*"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def _write(dest: Path, rows: list[tuple[str, dict[str, Any]]]) -> None:
    with gzip.open(dest, "wt", encoding="utf-8") as fh:
        for name, doc in rows:
            fh.write(json_util.dumps({"c": name, "d": doc}, ensure_ascii=False))
            fh.write("\n")


async def export_database(
    db: Any, backup_dir: Path, *, keep_days: int = KEEP_DAYS, now: datetime | None = None
) -> Path:
    """Barcha kolleksiyalarni `bot-YYYYmmdd-HHMMSS.jsonl.gz` ga yozadi (qator: {"c": nomi, "d": hujjat})."""
    await asyncio.to_thread(backup_dir.mkdir, parents=True, exist_ok=True)
    rows: list[tuple[str, dict[str, Any]]] = []
    for name in sorted(await db.list_collection_names()):
        if name in SKIP_COLLECTIONS:
            continue
        for doc in await db[name].find({}).to_list(None):
            rows.append((name, doc))
    dest = backup_dir / f"bot-{(now or utcnow()).strftime('%Y%m%d-%H%M%S')}.jsonl.gz"
    await asyncio.to_thread(_write, dest, rows)
    await asyncio.to_thread(prune_backups, backup_dir, keep_days)
    return dest


class BackupService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    async def run(self) -> Path | None:
        now = self.clock()
        dest = await export_database(self.ctx.repo.db, self.ctx.settings.data_path / "backups", now=now)
        logger.info("Backup tayyor: {}", dest)
        size = await asyncio.to_thread(lambda: dest.stat().st_size)
        if to_tz(now, self.ctx.settings.tz).weekday() == SEND_WEEKDAY and size <= MAX_SEND_BYTES:
            data = await asyncio.to_thread(dest.read_bytes)
            for admin_id in self.ctx.settings.admin_ids:
                try:
                    await self.ctx.sender.send_document(
                        admin_id, data, dest.name, "🗄 Haftalik backup (MongoDB)"
                    )
                except Exception as exc:
                    logger.warning("Backup adminga yuborilmadi: {}", exc)
        return dest
