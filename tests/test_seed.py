from app.collectors.seed import SEED_SOURCES, seed_sources
from app.collectors.service import FETCHERS
from app.content.schedule import ALL_CATEGORIES, NEWS_CATEGORIES


async def test_seed_sources_idempotent(repo) -> None:
    first = await seed_sources(repo)
    second = await seed_sources(repo)
    assert first == len(SEED_SOURCES)
    assert second == 0
    assert await repo.sources.count() == len(SEED_SOURCES)


def test_seed_sources_have_known_types_and_categories() -> None:
    urls = set()
    for src in SEED_SOURCES:
        assert src["type"] in FETCHERS, src
        assert src["category"] in {*ALL_CATEGORIES, "mahalliy"}, src
        assert 1 <= src["trust"] <= 5
        assert src["url"].startswith("https://")
        assert src["url"] not in urls
        urls.add(src["url"])
    kinds = {s["type"] for s in SEED_SOURCES}
    assert {"rss", "cisa_kev", "nvd", "hackernews", "github"} <= kinds


async def test_seed_adds_missing_sources_to_existing_db(repo) -> None:
    from app.db.models import Source

    await repo.sources.insert(Source(name="Eski", type="rss", url=SEED_SOURCES[0]["url"], category="kiber"))
    added = await seed_sources(repo)
    assert added == len(SEED_SOURCES) - 1
    assert await repo.sources.count() == len(SEED_SOURCES)


def test_every_news_category_has_sources() -> None:
    cats = {s["category"] for s in SEED_SOURCES if s.get("enabled", True)}
    assert set(NEWS_CATEGORIES) <= cats
