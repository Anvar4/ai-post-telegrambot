from sqlalchemy import func, select

from app.collectors.seed import SEED_SOURCES, seed_sources
from app.collectors.service import FETCHERS
from app.db.models import Source


async def test_seed_sources_idempotent(repo) -> None:
    first = await seed_sources(repo)
    second = await seed_sources(repo)
    assert first == len(SEED_SOURCES)
    assert second == 0
    async with repo.session() as s:
        assert await s.scalar(select(func.count()).select_from(Source)) == len(SEED_SOURCES)


def test_seed_sources_have_known_types_and_categories() -> None:
    urls = set()
    for src in SEED_SOURCES:
        assert src["type"] in FETCHERS, src
        assert src["category"] in {"kiber", "yangilik", "ai", "ilova", "sayt", "mahalliy"}, src
        assert 1 <= src["trust"] <= 5
        assert src["url"].startswith("https://")
        assert src["url"] not in urls
        urls.add(src["url"])
    kinds = {s["type"] for s in SEED_SOURCES}
    assert {"rss", "cisa_kev", "nvd", "hackernews", "github"} <= kinds
