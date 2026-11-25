"""Boshlang'ich manbalar (SPEC ilovasi). URL'lar 2026-11-06 va 2026-11-25 da tekshirilgan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    # --- v2: butun texnologiya dunyosi ---
    # Umumiy texnologiya
    {
        "name": "Wired",
        "type": "rss",
        "category": "yangilik",
        "trust": 4,
        "lang": "en",
        "url": "https://www.wired.com/feed/rss",
    },
    {
        "name": "The Register",
        "type": "rss",
        "category": "yangilik",
        "trust": 4,
        "lang": "en",
        "url": "https://www.theregister.com/headlines.atom",
    },
    {
        "name": "3DNews",
        "type": "rss",
        "category": "yangilik",
        "trust": 3,
        "lang": "ru",
        "url": "https://3dnews.ru/news/rss/",
    },
    # Sun'iy intellekt
    {
        "name": "MIT Technology Review (AI)",
        "type": "rss",
        "category": "ai",
        "trust": 5,
        "lang": "en",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    },
    {
        "name": "TechCrunch AI",
        "type": "rss",
        "category": "ai",
        "trust": 4,
        "lang": "en",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    # Dasturlash
    {
        "name": "GitHub Blog",
        "type": "rss",
        "category": "dasturlash",
        "trust": 5,
        "lang": "en",
        "url": "https://github.blog/feed/",
    },
    {
        "name": "Stack Overflow Blog",
        "type": "rss",
        "category": "dasturlash",
        "trust": 4,
        "lang": "en",
        "url": "https://stackoverflow.blog/feed/",
    },
    {
        "name": "The New Stack",
        "type": "rss",
        "category": "dasturlash",
        "trust": 4,
        "lang": "en",
        "url": "https://thenewstack.io/feed/",
    },
    {
        "name": "InfoQ",
        "type": "rss",
        "category": "dasturlash",
        "trust": 4,
        "lang": "en",
        "url": "https://feed.infoq.com/",
    },
    # Smartfon va gadjetlar
    {
        "name": "GSMArena",
        "type": "rss",
        "category": "gadjet",
        "trust": 4,
        "lang": "en",
        "url": "https://www.gsmarena.com/rss-news-reviews.php3",
    },
    {
        "name": "Engadget",
        "type": "rss",
        "category": "gadjet",
        "trust": 4,
        "lang": "en",
        "url": "https://www.engadget.com/rss.xml",
    },
    {
        "name": "9to5Google",
        "type": "rss",
        "category": "gadjet",
        "trust": 4,
        "lang": "en",
        "url": "https://9to5google.com/feed/",
    },
    {
        "name": "9to5Mac",
        "type": "rss",
        "category": "gadjet",
        "trust": 4,
        "lang": "en",
        "url": "https://9to5mac.com/feed/",
    },
    {
        "name": "Android Authority",
        "type": "rss",
        "category": "gadjet",
        "trust": 4,
        "lang": "en",
        "url": "https://www.androidauthority.com/feed/",
    },
    {
        "name": "Tom's Hardware",
        "type": "rss",
        "category": "gadjet",
        "trust": 4,
        "lang": "en",
        "url": "https://www.tomshardware.com/feeds/all",
    },
    # Robototexnika
    {
        "name": "IEEE Spectrum Robotics",
        "type": "rss",
        "category": "robot",
        "trust": 5,
        "lang": "en",
        "url": "https://spectrum.ieee.org/feeds/topic/robotics.rss",
    },
    {
        "name": "The Robot Report",
        "type": "rss",
        "category": "robot",
        "trust": 4,
        "lang": "en",
        "url": "https://www.therobotreport.com/feed/",
    },
    {
        "name": "Robohub",
        "type": "rss",
        "category": "robot",
        "trust": 3,
        "lang": "en",
        "url": "https://robohub.org/feed/",
    },
    # Kripto va blokcheyn
    {
        "name": "CoinDesk",
        "type": "rss",
        "category": "kripto",
        "trust": 4,
        "lang": "en",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    },
    {
        "name": "Cointelegraph",
        "type": "rss",
        "category": "kripto",
        "trust": 3,
        "lang": "en",
        "url": "https://cointelegraph.com/rss",
    },
    {
        "name": "Decrypt",
        "type": "rss",
        "category": "kripto",
        "trust": 3,
        "lang": "en",
        "url": "https://decrypt.co/feed",
    },
    # Avtomobil texnologiyalari
    {
        "name": "Electrek",
        "type": "rss",
        "category": "avto",
        "trust": 4,
        "lang": "en",
        "url": "https://electrek.co/feed/",
    },
    {
        "name": "InsideEVs",
        "type": "rss",
        "category": "avto",
        "trust": 4,
        "lang": "en",
        "url": "https://insideevs.com/rss/articles/all/",
    },
    {
        "name": "Carscoops",
        "type": "rss",
        "category": "avto",
        "trust": 3,
        "lang": "en",
        "url": "https://www.carscoops.com/feed/",
    },
    {
        "name": "TechCrunch Transportation",
        "type": "rss",
        "category": "avto",
        "trust": 4,
        "lang": "en",
        "url": "https://techcrunch.com/category/transportation/feed/",
    },
    # Kosmos va fan
    {
        "name": "NASA",
        "type": "rss",
        "category": "kosmos",
        "trust": 5,
        "lang": "en",
        "url": "https://www.nasa.gov/news-release/feed/",
    },
    {
        "name": "Space.com",
        "type": "rss",
        "category": "kosmos",
        "trust": 4,
        "lang": "en",
        "url": "https://www.space.com/feeds/all",
    },
    {
        "name": "SpaceNews",
        "type": "rss",
        "category": "kosmos",
        "trust": 4,
        "lang": "en",
        "url": "https://spacenews.com/feed/",
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
    """Roʻyxatdagi, lekin bazada hali yoʻq manbalarni (URL boʻyicha) qoʻshadi; mavjudlariga tegmaydi."""
    existing = {s.url for s in await repo.sources.find({})}
    added = 0
    for item in SEED_SOURCES:
        if item["url"] in existing:
            continue
        await repo.sources.insert(
            Source(enabled=item.get("enabled", True), **{k: v for k, v in item.items() if k != "enabled"})
        )
        added += 1
    return added
