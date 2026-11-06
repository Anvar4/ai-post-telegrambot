import json
from datetime import UTC, datetime, timedelta

import httpx
import respx

from app.collectors import cisa_kev, github, hackernews, nvd, rss
from app.collectors.base import FetchContext
from app.collectors.dedupe import attach_to_story, title_similarity
from app.collectors.extract import extract_text
from app.collectors.normalize import canonical_url, url_hash
from app.collectors.service import CollectorService
from app.db.models import Article, Source, Story

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
FCTX = FetchContext(now=NOW)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Sec</title>
<item><title>Chrome zero-day exploited in attacks</title>
<link>https://news.example.com/chrome-0day?utm_source=rss&amp;utm_medium=feed</link>
<description>&lt;p&gt;Google patched &lt;b&gt;CVE-2026-1234&lt;/b&gt;.&lt;/p&gt;</description>
<pubDate>Fri, 06 Nov 2026 09:00:00 GMT</pubDate></item>
<item><title>Old story</title><link>https://news.example.com/old</link>
<pubDate>Fri, 02 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def src(**kw) -> Source:
    values = {
        "id": 1,
        "name": "Test",
        "type": "rss",
        "url": "https://news.example.com/feed",
        "category": "kiber",
        "trust": 4,
        "lang": "en",
        "enabled": True,
        "fail_count": 0,
    }
    values.update(kw)
    return Source(**values)


# --- normallashtirish ---


def test_canonical_strips_tracking() -> None:
    url = "HTTPS://Example.COM/a/b/?utm_source=x&id=5&fbclid=y&ref=tw#frag"
    assert canonical_url(url) == "https://example.com/a/b?id=5"


def test_canonical_sorts_query_and_keeps_root_slash() -> None:
    assert canonical_url("https://a.com/p?b=2&a=1") == "https://a.com/p?a=1&b=2"
    assert canonical_url("https://a.com/") == "https://a.com/"
    assert canonical_url("https://a.com") == "https://a.com/"


def test_same_url_same_hash() -> None:
    assert url_hash("https://a.com/x?utm_campaign=1") == url_hash("https://A.com/x/")
    assert url_hash("https://a.com/x") != url_hash("https://a.com/y")


# --- dublikatlar ---


def test_title_similarity_threshold_cases() -> None:
    assert (
        title_similarity(
            "Google patches Chrome zero-day exploited in attacks",
            "Google Patches Chrome Zero-Day Exploited in Attacks!",
        )
        >= 85
    )
    assert title_similarity("Google patches Chrome zero-day", "Apple releases iOS 27 beta") < 50


async def test_similar_titles_merge_into_story(repo) -> None:
    a1 = Article(
        url="https://a.com/1", url_hash="h1", title="Microsoft fixes Windows zero-day exploited in attacks"
    )
    a2 = Article(
        url="https://b.com/2",
        url_hash="h2",
        title="Microsoft fixes Windows zero-day exploited in the attacks",
    )
    st1 = await attach_to_story(repo, a1, category="kiber", now=NOW)
    st2 = await attach_to_story(repo, a2, category="kiber", now=NOW + timedelta(hours=1))
    assert st1.id == st2.id
    assert a2.story_id == st1.id
    assert (await repo.stories.get(st1.id)).article_count == 2


async def test_old_story_outside_48h_not_merged(repo) -> None:
    title = "Microsoft fixes Windows zero-day exploited in attacks"
    await repo.stories.insert(
        Story(title=title, first_seen=NOW - timedelta(hours=50), last_seen=NOW - timedelta(hours=50))
    )
    story = await attach_to_story(
        repo, Article(url="https://a.com/1", url_hash="h1", title=title), category="kiber", now=NOW
    )
    assert await repo.stories.count() == 2
    assert story.article_count == 1


# --- parserlar ---


def test_rss_parse_fixture() -> None:
    items = rss.parse(RSS.encode(), src(), FCTX)
    assert len(items) == 1  # 7 kundan eski yozuv tashlanadi
    item = items[0]
    assert item.url == "https://news.example.com/chrome-0day"
    assert item.title == "Chrome zero-day exploited in attacks"
    assert item.summary == "Google patched CVE-2026-1234."
    assert item.published_at == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def test_cisa_kev_recent_only() -> None:
    data = {
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-1111",
                "vendorProject": "Microsoft",
                "product": "Windows",
                "vulnerabilityName": "Windows Privilege Escalation",
                "dateAdded": "2026-11-05",
                "shortDescription": "Desc",
                "requiredAction": "Apply updates",
                "dueDate": "2026-11-26",
                "knownRansomwareCampaignUse": "Known",
            },
            {
                "cveID": "CVE-2026-0001",
                "vendorProject": "X",
                "product": "Y",
                "vulnerabilityName": "Old",
                "dateAdded": "2026-10-01",
                "shortDescription": "d",
                "requiredAction": "a",
                "dueDate": "2026-10-20",
                "knownRansomwareCampaignUse": "Unknown",
            },
        ]
    }
    items = cisa_kev.parse(json.dumps(data).encode(), src(type="cisa_kev"), FCTX)
    assert len(items) == 1
    assert items[0].url == "https://nvd.nist.gov/vuln/detail/CVE-2026-1111"
    assert "CVE-2026-1111" in items[0].title and "Microsoft" in items[0].title
    assert "Apply updates" in items[0].summary
    assert items[0].extra["cve"] == "CVE-2026-1111"


def test_nvd_parses_items() -> None:
    data = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2026-2222",
                    "published": "2026-11-06T08:15:00.000",
                    "descriptions": [
                        {"lang": "es", "value": "es"},
                        {"lang": "en", "value": "RCE in Foo Server 2.1"},
                    ],
                    "metrics": {
                        "cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]
                    },
                }
            }
        ]
    }
    items = nvd.parse(json.dumps(data).encode(), src(type="nvd"), FCTX)
    assert items[0].url == "https://nvd.nist.gov/vuln/detail/CVE-2026-2222"
    assert "RCE in Foo Server" in items[0].title
    assert items[0].extra["cvss"] == 9.8


@respx.mock
async def test_hn_filters_without_url_and_low_score() -> None:
    respx.get("https://hacker-news.firebaseio.com/v0/topstories.json").mock(
        return_value=httpx.Response(200, json=[1, 2, 3])
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/1.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "type": "story",
                "title": "Show HN: Tool",
                "url": "https://tool.dev",
                "score": 300,
                "descendants": 40,
                "time": int(NOW.timestamp()),
            },
        )
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/2.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "type": "story",
                "title": "Ask HN: no url",
                "score": 500,
                "time": int(NOW.timestamp()),
            },
        )
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/3.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 3,
                "type": "story",
                "title": "Low",
                "url": "https://low.dev",
                "score": 5,
                "time": int(NOW.timestamp()),
            },
        )
    )
    async with httpx.AsyncClient() as http:
        items = await hackernews.fetch(
            http, src(type="hackernews", url="https://hacker-news.firebaseio.com/v0/topstories.json"), FCTX
        )
    assert [i.url for i in items] == ["https://tool.dev/"]


@respx.mock
async def test_github_search_items() -> None:
    route = respx.get(url__startswith="https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "html_url": "https://github.com/acme/tool",
                        "full_name": "acme/tool",
                        "description": "Fast tool",
                        "stargazers_count": 900,
                        "language": "Rust",
                        "homepage": "https://tool.acme.dev",
                        "created_at": "2026-11-02T10:00:00Z",
                    }
                ]
            },
        )
    )
    async with httpx.AsyncClient() as http:
        items = await github.fetch(
            http,
            src(type="github", url="https://api.github.com/search/repositories", category="ilova"),
            FetchContext(now=NOW, github_token="ghp_x"),
        )
    assert items[0].url == "https://github.com/acme/tool"
    assert items[0].extra["stars"] == 900
    req = route.calls[0].request
    assert "created%3A%3E2026-10-30" in str(req.url) or "created:>2026-10-30" in str(req.url)
    assert req.headers["authorization"] == "Bearer ghp_x"


@respx.mock
async def test_extract_text_from_html() -> None:
    html = (
        "<html><head><title>T</title></head><body><nav>menu</nav><article><h1>Sarlavha</h1>"
        + "<p>Google Chrome uchun favqulodda yangilanish chiqardi va zaiflikni yopdi. </p>" * 5
        + "</article></body></html>"
    )
    respx.get("https://a.com/x").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    async with httpx.AsyncClient() as http:
        text = await extract_text(http, "https://a.com/x")
    assert text is not None and "favqulodda yangilanish" in text


# --- servis ---


@respx.mock
async def test_collector_service_inserts_and_skips_existing(repo) -> None:
    await repo.sources.insert(src(id=None))
    respx.get("https://news.example.com/feed").mock(return_value=httpx.Response(200, content=RSS.encode()))
    async with httpx.AsyncClient() as http:
        svc = CollectorService(repo, http, notifier=None, clock=lambda: NOW)
        first = await svc.run_once()
        second = await svc.run_once()
    assert first.new_articles == 1 and first.new_stories == 1
    assert second.new_articles == 0
    (story,) = await repo.stories.find({})
    (source,) = await repo.sources.find({})
    assert story.source_category == "kiber"
    assert source.last_ok_at is not None and source.fail_count == 0


@respx.mock
async def test_source_disabled_after_three_failures(repo) -> None:
    from tests.fakes import FakeNotifier

    await repo.sources.insert(src(id=None))
    respx.get("https://news.example.com/feed").mock(return_value=httpx.Response(500))
    notifier = FakeNotifier()
    async with httpx.AsyncClient() as http:
        svc = CollectorService(repo, http, notifier=notifier, clock=lambda: NOW)
        for _ in range(3):
            stats = await svc.run_once()
    (source,) = await repo.sources.find({})
    assert stats.failed_sources == 1
    assert source.enabled is False
    assert source.fail_count == 3
    assert source.auto_disabled_at is not None
    assert len(notifier.messages) == 1


@respx.mock
async def test_auto_disabled_source_is_retried_after_6h(repo) -> None:
    from tests.fakes import FakeNotifier

    await repo.sources.insert(
        src(id=None, enabled=False, fail_count=3, auto_disabled_at=NOW - timedelta(hours=7))
    )
    await repo.sources.insert(
        src(id=None, name="Admin off", url="https://off.example.com/feed", enabled=False)
    )
    respx.get("https://news.example.com/feed").mock(return_value=httpx.Response(200, content=RSS.encode()))
    off = respx.get("https://off.example.com/feed").mock(
        return_value=httpx.Response(200, content=RSS.encode())
    )
    notifier = FakeNotifier()
    async with httpx.AsyncClient() as http:
        await CollectorService(repo, http, notifier=notifier, clock=lambda: NOW).run_once()
    sources = {x.name: x for x in await repo.sources.find({})}
    assert sources["Test"].enabled is True
    assert sources["Test"].auto_disabled_at is None
    assert sources["Admin off"].enabled is False
    assert not off.called


async def test_story_batch_defers_writes_until_flush(repo) -> None:
    from app.collectors.dedupe import StoryBatch

    batch = StoryBatch(ids=iter(await repo.next_ids("stories", 2)))
    candidates: list = []
    a1 = Article(url="https://a.com/1", url_hash="h1", title="Chrome zero-day exploited in attacks now")
    a2 = Article(url="https://b.com/2", url_hash="h2", title="Chrome zero-day exploited in attacks now!")
    s1 = await attach_to_story(repo, a1, category="kiber", now=NOW, candidates=candidates, batch=batch)
    s2 = await attach_to_story(repo, a2, category="kiber", now=NOW, candidates=candidates, batch=batch)
    assert s1 is s2 and s1.article_count == 2
    assert await repo.stories.count() == 0  # hali yozilmagan
    await batch.flush(repo)
    (saved,) = await repo.stories.find({})
    assert saved.article_count == 2 and a1.story_id == a2.story_id == saved.id
