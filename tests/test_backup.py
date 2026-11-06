import gzip
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from app import healthcheck
from app.db.models import Post
from app.utils.backup import BackupService, export_database, prune_backups
from app.utils.heartbeat import touch_heartbeat


async def test_export_database_writes_all_collections(repo, tmp_path: Path) -> None:
    await repo.posts.insert(
        Post(kind="news", text_html="salom", created_at=datetime(2026, 11, 6, tzinfo=UTC))
    )
    await repo.set_setting("rt:paused", False)
    dest = await export_database(repo.db, tmp_path / "backups", now=datetime(2026, 11, 6, 3, 0, tzinfo=UTC))
    assert dest.name == "bot-20261106-030000.jsonl.gz"
    lines = [json.loads(line) for line in gzip.open(dest, "rt", encoding="utf-8")]
    by_coll = {line["c"] for line in lines}
    assert {"posts", "settings", "counters"} <= by_coll
    post = next(line["d"] for line in lines if line["c"] == "posts")
    assert post["text_html"] == "salom" and post["_id"] == 1


def test_prune_backups_keeps_7_days(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    old = folder / "bot-20261020-030000.jsonl.gz"
    new = folder / "bot-20261105-030000.jsonl.gz"
    other = folder / "notes.txt"
    for f in (old, new, other):
        f.write_text("x")
    old_time = time.time() - 10 * 86400
    os.utime(old, (old_time, old_time))
    os.utime(other, (old_time, old_time))
    assert prune_backups(folder, keep_days=7) == 1
    assert not old.exists() and new.exists() and other.exists()


async def test_backup_service_weekly_sends_file_to_admin(ctx) -> None:
    await ctx.repo.posts.insert(Post(kind="news", text_html="x"))
    monday = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    path = await BackupService(ctx, clock=lambda: monday).run()
    assert path is not None and path.exists()
    docs = [m for m in ctx.sender.sent if m.method == "document"]
    assert [d.chat_id for d in docs] == [1]
    ctx.sender.sent.clear()
    await BackupService(ctx, clock=lambda: datetime(2026, 11, 10, 3, 0, tzinfo=UTC)).run()
    assert [m for m in ctx.sender.sent if m.method == "document"] == []


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
