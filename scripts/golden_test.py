"""«Oltin» test (SPEC 13): 5 ta haqiqiy maqola → post → fakt-tekshiruv (haqiqiy API, qo'lda).

Telegram'ga HECH NARSA yubormaydi — natijalar faqat konsolga va data/golden/ ga yoziladi.
Ishlatish:  python scripts/golden_test.py [N]     (standart N=5; .env dagi AI kalitlari kerak)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ai.providers.factory import build_clients
from app.ai.router import AIRouter
from app.collectors.seed import seed_sources
from app.collectors.service import CollectorService
from app.config import get_settings
from app.context import AppContext
from app.db.mongo import connect, ensure_indexes
from app.db.repo import Repo
from app.main import USER_AGENT
from app.pipeline.orchestrator import Pipeline
from app.pipeline.state import PostKind
from app.pipeline.write import draft_with_checks
from app.utils.runtime import Runtime


class ConsoleSender:
    """Telegram o'rniga — hech narsa yubormaydi."""

    async def send_message(self, chat_id: int, text: str, **_: Any) -> int:
        return 0

    async def send_photo(self, chat_id: int, photo: bytes, caption: str | None = None, **_: Any) -> int:
        return 0


class ConsoleNotifier:
    async def notify(self, text: str, *, key: str | None = None, html: bool = False) -> None:
        print(f"[admin] {text}")


async def main(n: int) -> int:
    settings = get_settings()
    out_dir = settings.data_path / "golden"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Alohida vaqtinchalik baza: asosiy bot bazasiga tegmaydi, oxirida o'chiriladi
    uri = settings.mongodb_uri.get_secret_value() if settings.mongodb_uri else ""
    client, db = connect(uri, f"{settings.mongodb_db}_golden")
    await client.drop_database(db.name)
    await ensure_indexes(db)
    repo = Repo(db, tz=settings.tz)
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as http:
        clients = build_clients(settings, http)
        for p in clients.problems:
            print("⚠️", p)
        router = AIRouter(clients.as_roles(), image=None, repo=repo, prices=settings.model_prices)
        ctx = AppContext(
            settings=settings,
            repo=repo,
            router=router,
            sender=ConsoleSender(),  # type: ignore[arg-type]
            notifier=ConsoleNotifier(),
            runtime=Runtime(repo, settings),
            salt="golden",
            http=http,
        )  # type: ignore[arg-type]
        await seed_sources(repo)
        stats = await CollectorService(repo, http, ConsoleNotifier()).run_once()
        print(f"Yig'ildi: {stats.new_articles} maqola, {stats.new_stories} story")
        pipeline = Pipeline(ctx)
        await pipeline.selector.score_new(limit=30)
        stories = await repo.stories.find(
            {"status": "scored", "category": {"$in": ["kiber", "yangilik", "ai"]}},
            sort=[("score", -1)],
            limit=n,
        )
        results = []
        for st in stories:
            kind = PostKind.ALERT if st.category == "kiber" else PostKind.NEWS
            m = await pipeline.story_material(st.id)
            res = await draft_with_checks(
                pipeline.writer,
                pipeline.checker,
                kind,
                source_text=m["source_text"],
                story_title=st.title,
                source_urls=m["urls"],
                source_name=m["source_name"],
                has_image=True,
                risk_flags=st.risk_flags or [],
                extra_allowed=m["extra_allowed"],
            )
            fabricated = [i for i in res.report.all_issues() if i.get("type") == "fabricated"]
            results.append(
                {
                    "story": st.title,
                    "score": st.score,
                    "verdict": res.report.verdict,
                    "rounds": res.rounds,
                    "fabricated": fabricated,
                    "text": res.output.text_html,
                    "issues": res.report.all_issues(),
                }
            )
            print("\n" + "=" * 80 + f"\n[{res.report.verdict.upper()}] ({st.score}) {st.title}\n" + "-" * 80)
            print(res.output.text_html)
        (out_dir / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        spent = await repo.spent_today()
    await client.drop_database(db.name)
    await client.close()
    passed = sum(1 for r in results if r["verdict"] == "pass" and not r["fabricated"])
    print(
        f"\nNatija: {passed}/{len(results)} post fakt-tekshiruvdan o'tdi, to'qima fakt yo'q. "
        f"Xarajat: ${spent:.4f}"
    )
    print(f"Batafsil: {out_dir / 'results.json'}")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)))
