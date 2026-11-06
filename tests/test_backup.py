import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from app import healthcheck
from app.utils.backup import BackupService, backup_sqlite, prune_backups
from app.utils.heartbeat import touch_heartbeat
from tests.conftest import make_settings


def make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("create table t (x int)")
    con.execute("insert into t values (42)")
    con.commit()
    con.close()


async def test_backup_creates_consistent_copy(tmp_path: Path) -> None:
    db = tmp_path / "bot.db"
    make_db(db)
    dest = await backup_sqlite(db, tmp_path / "backups", now=datetime(2026, 11, 6, 3, 0, tzinfo=UTC))
    assert dest.name == "bot-20261106-030000.db"
    con = sqlite3.connect(dest)
    assert con.execute("select x from t").fetchone() == (42,)
    con.close()


def test_prune_backups_keeps_7_days(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    old = folder / "bot-20261020-030000.db"
    new = folder / "bot-20261105-030000.db"
    other = folder / "notes.txt"
    for f in (old, new, other):
        f.write_text("x")
    old_time = time.time() - 10 * 86400
    os.utime(old, (old_time, old_time))
    os.utime(other, (old_time, old_time))
    assert prune_backups(folder, keep_days=7) == 1
    assert not old.exists() and new.exists() and other.exists()


async def test_backup_service_weekly_sends_file_to_admin(ctx, tmp_path: Path) -> None:
    db = tmp_path / "bot.db"
    make_db(db)
    ctx.settings = make_settings(tmp_path, database_url=f"sqlite+aiosqlite:///{db.as_posix()}")
    monday = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    path = await BackupService(ctx, clock=lambda: monday).run()
    assert path is not None and path.exists()
    docs = [m for m in ctx.sender.sent if m.method == "document"]
    assert [d.chat_id for d in docs] == [1]
    ctx.sender.sent.clear()
    await BackupService(ctx, clock=lambda: datetime(2026, 11, 10, 3, 0, tzinfo=UTC)).run()
    assert [m for m in ctx.sender.sent if m.method == "document"] == []


async def test_backup_service_skips_non_sqlite(ctx, tmp_path: Path) -> None:
    ctx.settings = make_settings(tmp_path, database_url="postgresql+asyncpg://u:p@h/db")
    assert await BackupService(ctx).run() is None


def test_healthcheck_ok_and_stale_kills(tmp_path: Path, monkeypatch) -> None:
    killed: list[int] = []
    monkeypatch.setattr(healthcheck.os, "kill", lambda pid, sig: killed.append(pid))
    touch_heartbeat(tmp_path / "heartbeat")
    (tmp_path / "bot.pid").write_text("4321")
    assert healthcheck.check(tmp_path) == 0
    assert killed == []
    stale = time.time() - 700
    os.utime(tmp_path / "heartbeat", (stale, stale))
    assert healthcheck.check(tmp_path) == 1
    assert killed == [4321]
