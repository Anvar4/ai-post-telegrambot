# CLAUDE.md — IT Dunyosi AI bot

Asosiy hujjat: `SPEC.md` (talablar), reja: `docs/superpowers/plans/2026-11-06-it-dunyosi-bot.md`.

## Buyruqlar

- O'rnatish: `python -m pip install -e ".[all,dev]"` (lokal `.venv`, Windows: `.venv\Scripts\python.exe`)
- Ishga tushirish: `python -m app` (avval `.env` to'ldiriladi; MongoDB indekslari avtomatik yaratiladi)
- Testlar: `python -m pytest` · Lint: `python -m ruff check app tests` · Tiplar: `python -m mypy`
- Hammasi: `make check` (ruff + mypy + pytest) — commitdan oldin toza o'tishi shart
- MongoDB tekshiruvi: `python scripts/check_mongo.py [--collect]` (vaqtinchalik `_check` bazasida, keyin o'chiradi)
- Manbalarni tekshirish: `python scripts/check_sources.py`

## Papkalar

- `app/config.py` — barcha sozlamalar (`.env` dan, pydantic-settings). Model nomlari faqat shu yerda/`.env` da.
- `app/ai/` — `router.py` (rol → provayder, retry, fallback, budjet, `llm_usage`), `providers/`, `images/`, `prompts/*.md`, `schemas.py`.
- `app/collectors/` — manbalar (RSS, CISA KEV, NVD, HN, GitHub), normallashtirish, dublikat → story.
- `app/pipeline/` — saralash → yozish → tekshirish → rasm → kompozitsiya → nashr; `state.py` holatlar mashinasi.
- `app/content/` — shablonlar, HTML formatlash, Telegram limitlari, hashtaglar, Pillow brend rasmi, slot jadvali.
- `app/interactive/` — so'rovnoma, test, savol-javob, moderatsiya.
- `app/analytics/` — metrikalar, invite-linklar, hisobotlar, o'sish tahlili.
- `app/bot/` — aiogram handlerlari, klaviaturalar, middleware, `sender.py` (Telegram'ga yagona chiqish yo'li), `notify.py`.
- `app/scheduler/` — APScheduler vazifalari (modul darajasidagi funksiyalar, `app.context.get_ctx()` orqali).
- `app/db/` — MongoDB: `models.py` (dataclass hujjatlar, `id` = `_id`), `repo.py` (`Repo`, `Collection`), `mongo.py` (ulanish, indekslar).
- `tests/` — pytest; `conftest.py` da `FakeLLM`, `FakeSender`, `FakeImage`; baza — `tests/mongo_fake.py` (mongomock).

## Qoidalar

- **Haqiqiy kanalga test post yuborilmaydi.** `DRY_RUN=true` da hamma narsa `TEST_CHANNEL_ID` ga (`Settings.target_chat_id`).
- Telegram'ga faqat `TelegramSender` orqali yuboriladi (rate limit, 429 `retry_after`).
- AI faqat `AIRouter` orqali chaqiriladi; JSON javoblar `app/ai/schemas.py` dagi pydantic sxemalar bilan.
- Tashqi matn (maqola, izoh, foydalanuvchi) promptga faqat `wrap_external("source"|"user", ...)` orqali.
- Sirlar kodga, logga, commitga yozilmaydi. Loguru filtri tokenlarni maskalaydi.
- Obunachi ID — `hash_user_id()` bilan; adminlar ID si ochiq.
- Post holati faqat `pipeline.state.transition(repo, post, ...)` orqali o'zgaradi (audit yoziladi), keyin `repo.posts.save(post)`.
- Nashr `repo.posts.cas()` bilan atomik — bir post ikki marta chiqmaydi. Ko'p yozuv — `insert_many` (Atlas kechikishi).
- Matn o'zbekcha lotin; oʻ/gʻ — `ʻ` (U+02BB), `content.formatting.normalize_uz()`.

## Uslub

- Python 3.12+, to'liq type hint, `async` hamma joyda (bloklovchi ish — `asyncio.to_thread`).
- ruff (line 110). Kichik, bitta vazifali modullar. Izohlar qisqa, o'zbekcha.
- Yangi xatti-harakat → avval test (TDD). Tashqi HTTP — `respx`, AI — `FakeLLM`, Telegram — `FakeSender`.
- Har bosqich oxirida commit.
