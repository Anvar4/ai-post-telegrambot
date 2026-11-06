"""Manbalarni tekshirish: har bir manbadan haqiqiy so'rov va nechta yozuv kelganini chiqaradi.

Ishlatish:  python scripts/check_sources.py           (boshlang'ich ro'yxat)
            python scripts/check_sources.py --db      (bot.db dagi manbalar)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.collectors.base import FetchContext
from app.collectors.seed import SEED_SOURCES
from app.collectors.service import FETCHERS
from app.db.models import Source
from app.main import USER_AGENT
from app.utils.timeutil import utcnow


async def load_sources(from_db: bool) -> list[Source]:
    if not from_db:
        return [
            Source(id=i, enabled=s.get("enabled", True), **{k: v for k, v in s.items() if k != "enabled"})
            for i, s in enumerate(SEED_SOURCES, 1)
        ]
    from app.config import get_settings
    from app.db.mongo import connect
    from app.db.repo import Repo

    s = get_settings()
    client, db = connect(s.mongodb_uri.get_secret_value() if s.mongodb_uri else "", s.mongodb_db)
    try:
        return await Repo(db).sources.find({}, sort=[("_id", 1)])
    finally:
        await client.close()


async def main() -> int:
    sources = await load_sources("--db" in sys.argv)
    fctx = FetchContext(now=utcnow())
    failed = 0
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as http:
        for src in sources:
            mark = "" if src.enabled else " (o'chiq)"
            try:
                items = await FETCHERS[src.type](http, src, fctx)
                sample = items[0].title[:60] if items else "—"
                print(f"OK   {src.name:<32} {len(items):>3} ta  {sample}{mark}")
            except Exception as exc:
                failed += 1
                print(f"XATO {src.name:<32} {type(exc).__name__}: {str(exc)[:80]}{mark}")
    print(f"\nJami: {len(sources)}, xato: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
