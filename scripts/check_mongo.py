"""MongoDB tekshiruvi: ulanish, indekslar, vaqt zonasi, atomik CAS, unique cheklov va real yig'ish sikli.

Vaqtinchalik `<MONGODB_DB>_check` bazasida ishlaydi va oxirida uni o'chiradi (asosiy bazaga tegmaydi).
Ishlatish:  python scripts/check_mongo.py [--collect]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from pymongo.errors import DuplicateKeyError

from app.config import load_settings
from app.db.models import Article, Post
from app.db.mongo import connect, ensure_indexes
from app.db.repo import Repo
from app.pipeline.state import PostStatus


async def main() -> int:
    settings, error = load_settings()
    if settings is None or settings.mongodb_uri is None:
        print(error or "MONGODB_URI .env da yo'q")
        return 1
    name = f"{settings.mongodb_db}_check"
    client, db = connect(settings.mongodb_uri.get_secret_value(), name)
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= cond
        print(f"{'OK ' if cond else 'XATO'} {label}")

    try:
        await client.drop_database(name)
        print("ulanish:", (await db.command("ping")).get("ok"))
        await ensure_indexes(db)
        await ensure_indexes(db)
        check("indekslar (2 marta chaqirildi)", True)
        repo = Repo(db, tz=settings.tz)

        local = datetime(2026, 11, 6, 10, 0, tzinfo=ZoneInfo("Asia/Tashkent"))
        post = await repo.posts.insert(Post(kind="news", status=PostStatus.SCHEDULED, scheduled_at=local))
        got = await repo.posts.get(post.id)
        expected = datetime(2026, 11, 6, 5, tzinfo=UTC)
        check("vaqt aware UTC qaytadi", got is not None and got.scheduled_at == expected)
        found = await repo.posts.find({"scheduled_at": {"$lte": local + timedelta(minutes=1)}})
        check("aware vaqt bilan filtr", len(found) == 1)
        check("avtomatik id", post.id == 1 and (await repo.posts.insert(Post(kind="tip"))).id == 2)

        results = await asyncio.gather(
            *(
                repo.posts.cas(post.id, {"status": PostStatus.SCHEDULED}, {"status": PostStatus.PUBLISHING})
                for _ in range(8)
            )  # type: ignore[arg-type]
        )
        check("CAS: 8 ta parallel urinishdan faqat 1 tasi o'tdi", results.count(True) == 1)

        await repo.articles.insert(Article(url="https://a.com/1", url_hash="dup", title="t"))
        try:
            await repo.articles.insert(Article(url="https://a.com/1", url_hash="dup", title="t"))
            check("url_hash unique", False)
        except DuplicateKeyError:
            check("url_hash unique (DuplicateKeyError)", True)

        await repo.set_setting("rt:slots", {"morning": "08:30"})
        check("sozlamalar", await repo.get_setting("rt:slots") == {"morning": "08:30"})

        if "--collect" in sys.argv:
            from app.collectors.seed import seed_sources
            from app.collectors.service import CollectorService
            from app.main import USER_AGENT

            await seed_sources(repo)
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
            ) as http:
                svc = CollectorService(repo, http, notifier=None)
                first = await svc.run_once()
                second = await svc.run_once()
            print(
                f"     yig'ish: {first.new_articles} maqola, {first.new_stories} story, "
                f"{first.failed_sources} xato; takror: {second.new_articles} yangi"
            )
            hashes = [a.url_hash for a in await repo.articles.find({})]
            check("real yig'ish (50+ maqola)", first.new_articles > 50)
            # Ikkinchi yig'ishda faqat shu orada chiqqan yangi yozuvlar bo'lishi mumkin
            unique = len(hashes) == len(set(hashes))
            check("takror yig'ishda dublikat yo'q", second.new_articles <= 5 and unique)
    finally:
        await client.drop_database(name)
        await client.close()
    print("\n✅ MongoDB tayyor." if ok else "\n⚠️  Muammolar bor.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
