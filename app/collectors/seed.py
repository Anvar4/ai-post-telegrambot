"""Boshlang'ich manbalar (SPEC ilovasi). URL'lar 2026-11-06 da tekshirilgan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db.models import Source

if TYPE_CHECKING:
    from app.db.repo import Repo

SEED_SOURCES: list[dict[str, Any]] = [
    # Kiberxavfsizlik
    {
        "name": "CISA KEV",
        "type": "cisa_kev",
        "category": "kiber",
        "trust": 5,
        "lang": "en",
        "url": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    },
    {
        "name": "NVD (kritik CVE)",
        "type": "nvd",
        "category": "kiber",
        "trust": 5,
        "lang": "en",
        "url": "https://services.nvd.nist.gov/rest/json/cves/2.0",
    },
    {
        "name": "The Hacker News",
        "type": "rss",
        "category": "kiber",
        "trust": 4,
        "lang": "en",
        "url": "https://feeds.feedburner.com/TheHackersNews",
    },
    {
        "name": "BleepingComputer",
        "type": "rss",
        "category": "kiber",
        "trust": 4,
        "lang": "en",
        "url": "https://www.bleepingcomputer.com/feed/",
    },
    {
        "name": "Krebs on Security",
        "type": "rss",
        "category": "kiber",
        "trust": 5,
        "lang": "en",
        "url": "https://krebsonsecurity.com/feed/",
    },
    {
        "name": "SecurityWeek",
        "type": "rss",
        "category": "kiber",
        "trust": 4,
        "lang": "en",
        "url": "https://www.securityweek.com/feed/",
    },
    {
        "name": "Dark Reading",
        "type": "rss",
        "category": "kiber",
        "trust": 4,
        "lang": "en",
        "url": "https://www.darkreading.com/rss.xml",
    },
    # The Record: 2026-11-06 da 520 xato (Cloudflare) — o'chiq, /sources orqali yoqish mumkin
    {
        "name": "The Record",
        "type": "rss",
        "category": "kiber",
        "trust": 4,
        "lang": "en",
        "url": "https://therecord.media/feed",
        "enabled": False,
    },
    {
        "name": "UZCERT",
        "type": "rss",
        "category": "kiber",
        "trust": 5,
        "lang": "uz",
        "url": "https://uzcert.uz/rss",
    },
    # IT va AI yangiliklari
    {
        "name": "TechCrunch",
        "type": "rss",
        "category": "yangilik",
        "trust": 4,
        "lang": "en",
        "url": "https://techcrunch.com/feed/",
    },
    {
        "name": "The Verge",
        "type": "rss",
        "category": "yangilik",
        "trust": 4,
        "lang": "en",
        "url": "https://www.theverge.com/rss/index.xml",
    },
    {
        "name": "Ars Technica",
        "type": "rss",
        "category": "yangilik",
        "trust": 4,
        "lang": "en",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
    },
    {
        "name": "Habr",
        "type": "rss",
        "category": "yangilik",
        "trust": 3,
        "lang": "ru",
        "url": "https://habr.com/ru/rss/articles/?fl=ru",
    },
    {
        "name": "OpenAI News",
        "type": "rss",
        "category": "ai",
        "trust": 5,
        "lang": "en",
        "url": "https://openai.com/news/rss.xml",
    },
    {
        "name": "Google AI Blog",
        "type": "rss",
        "category": "ai",
        "trust": 5,
        "lang": "en",
        "url": "https://blog.google/technology/ai/rss/",
    },
    {
        "name": "Google DeepMind",
        "type": "rss",
        "category": "ai",
        "trust": 5,
        "lang": "en",
        "url": "https://deepmind.google/blog/rss.xml",
    },
    # Ilova va saytlar
    {
        "name": "Hacker News",
        "type": "hackernews",
        "category": "yangilik",
        "trust": 3,
        "lang": "en",
        "url": "https://hacker-news.firebaseio.com/v0/topstories.json",
    },
    {
        "name": "GitHub (haftaning trend repolari)",
        "type": "github",
        "category": "ilova",
        "trust": 3,
        "lang": "en",
        "url": "https://api.github.com/search/repositories",
    },
    # Mahalliy (faqat texnologiyaga oidlari saralovchidan o'tadi)
    {
        "name": "Kun.uz",
        "type": "rss",
        "category": "mahalliy",
        "trust": 3,
        "lang": "uz",
        "url": "https://kun.uz/news/rss",
    },
    {
        "name": "Spot.uz",
        "type": "rss",
        "category": "mahalliy",
        "trust": 3,
        "lang": "ru",
        "url": "https://www.spot.uz/rss/",
    },
]


async def seed_sources(repo: Repo) -> int:
    """Manbalar jadvali bo'sh bo'lsa, boshlang'ich ro'yxatni qo'shadi."""
    async with repo.session() as s:
        if await s.scalar(select(func.count()).select_from(Source)):
            return 0
        for item in SEED_SOURCES:
            s.add(
                Source(enabled=item.get("enabled", True), **{k: v for k, v in item.items() if k != "enabled"})
            )
        await s.commit()
    return len(SEED_SOURCES)
