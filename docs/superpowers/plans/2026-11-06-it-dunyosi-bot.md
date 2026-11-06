# IT Dunyosi AI bot — amalga oshirish rejasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "IT Dunyosi" Telegram kanali uchun kontent topadigan, yozadigan, tekshiradigan, rasm chizadigan, jadval bo'yicha chiqaradigan, obunachilar bilan ishlaydigan va adminga hisobot beradigan avtonom AI-administrator bot.

**Architecture:** Bitta asyncio jarayoni: aiogram 3 (long polling) + APScheduler 3 (AsyncIOScheduler, SQLAlchemyJobStore) + kontent quvuri. Holat SQLite'da (SQLAlchemy 2 async + Alembic). Barcha AI chaqiruvlari `app/ai/router.py` orqali: rol → provayder, budjet, retry, fallback, `llm_usage`. Telegram'ga yuborish `TelegramSender` protokoli orqali (testda `FakeSender`).

**Tech Stack:** Python 3.12+ (lokal 3.14, Docker 3.12-slim), aiogram 3.31+, APScheduler 3.x, SQLAlchemy 2 + aiosqlite + Alembic, httpx + tenacity, feedparser, trafilatura, rapidfuzz, Pillow, pydantic-settings, loguru, openai / anthropic / google-genai, pytest + pytest-asyncio + respx, ruff + mypy.

**Spec:** `SPEC.md`

## Global Constraints

- Barcha postlar o'zbek tilida, lotin yozuvida; oʻ/gʻ — `ʻ` (U+02BB). Vaqt zonasi `Asia/Tashkent`.
- `DRY_RUN=true` bo'lsa har qanday yuborish faqat `TEST_CHANNEL_ID` ga; haqiqiy `CHANNEL_ID` ga hech qachon.
- Sirlar faqat `.env` dan; logda maskalanadi; `.env` va `data/` — `.gitignore` da.
- Model nomlari faqat `.env`/config'da (`OPENAI_EDITOR_MODEL=gpt-6-sol`, `OPENAI_FAST_MODEL=gpt-6-luna`).
- Har AI chaqiruvi: timeout, 3 urinish (exponential backoff), `llm_usage` ga token va narx. JSON javob pydantic sxema bilan; mos kelmasa 1 qayta so'rov, keyin xato.
- Telegram limitlari: caption ≤ 1024, xabar ≤ 4096, so'rovnoma savoli ≤ 300, variant ≤ 100, tushuntirish ≤ 200, variantlar 2–12. Chatga sekundiga ≤ 1 xabar, 429 → `retry_after`.
- Post uzunligi 500–900 belgi; `title_short` ≤ 60; Q&A javobi ≤ 700.
- Obunachi Telegram ID'lari tuzli HMAC bilan xeshlanadi (adminlardan tashqari); `qa_logs`, `moderation_events` 90 kundan keyin o'chadi.
- Postdagi havola domeni manba/story domenlaridan yoki rasmiy saytdan bo'lishi shart; aks holda post rad etiladi.
- Bot hech qachon obunachi matnini avtomatik kanalga chiqarmaydi; tashqi matn `<source>`/`<user>` teglarida.

## Review Focus

1. **`.env` dagi bo'sh qiymatlar va izohlar** (`CHANNEL_ID=` bo'sh, `ADMIN_IDS=1,2`) — config xatosiz yuklanishi, bo'sh qiymat `None` bo'lishi kerak → Task 1 testlari.
2. **AI model noto'g'ri JSON yoki markdown ```json bilan o'ralgan JSON qaytarsa** — kod bloki tozalanadi, 1 qayta so'rov, keyin `SchemaError` → Task 4 testi.
3. **Qayta ishga tushganda `PUBLISHING` holatidagi post** — `message_id` bor bo'lsa PUBLISHED, yo'q bo'lsa FAILED + adminga xabar, hech qachon qayta yuborilmaydi → Task 6 testi.
4. **Jim soatlarda (23:00–07:00) shoshilinch post** — 07:30 ga suriladi, kuniga ≤ 1 → Task 11 testi.
5. **AI o'ylab topgan URL yoki `</source>` bilan prompt injection** — post rad etiladi / teg neytrallanadi → Task 3 va Task 10 testlari.

---

## Fayl tuzilmasi

```
app/
  __main__.py, main.py, config.py, context.py, logging_setup.py
  db/        models.py, session.py, repo.py
  ai/        types.py, router.py, pricing.py, schemas.py, prompts.py, prompts/*.md
             providers/ openai.py, anthropic.py, gemini.py, openai_compat.py, factory.py
             images/    openai_img.py, gemini_img.py, stability_img.py, replicate_img.py, fal_img.py
  collectors/ base.py, normalize.py, rss.py, cisa_kev.py, nvd.py, hackernews.py, github.py,
             extract.py, dedupe.py, service.py, seed.py
  pipeline/  state.py, select.py, write.py, check.py, links.py, image.py, compose.py,
             publish.py, orchestrator.py
  content/   templates.py, formatting.py, limits.py, hashtags.py, brand_image.py, schedule.py
  interactive/ polls.py, quizzes.py, qa.py, moderation.py, ratelimit.py
  analytics/ metrics.py, invites.py, reports.py, growth.py
  bot/       sender.py, notify.py, keyboards.py, middlewares.py, setup.py,
             handlers/ admin.py, approval.py, qa.py, group.py, updates.py
  scheduler/ jobs.py, setup.py
  utils/     http.py, budget.py, timeutil.py, security.py, backup.py, heartbeat.py
alembic/  alembic.ini
tests/   conftest.py (in-memory DB, FakeLLM, FakeSender, FakeImage), test_*.py
```

---

## Bosqich 0 — Reja

### Task 0: Repo poydevori

**Files:** Create `CLAUDE.md`, `.gitignore`, `.dockerignore`, `pyproject.toml`, `.env.example`, `Makefile`.

- [ ] `pyproject.toml`: majburiy deps (aiogram>=3.31, apscheduler>=3.10,<4, sqlalchemy[asyncio]>=2, aiosqlite, alembic, httpx, tenacity, feedparser, trafilatura, rapidfuzz, pillow, pydantic>=2, pydantic-settings, loguru, openai); extras `anthropic`, `gemini`, `all`, `dev`. pytest `asyncio_mode=auto`; ruff (line 110, py312); mypy.
- [ ] `.env.example` — SPEC 2-bo'limdagi kalitlar, izohlar alohida qatorda (inline izoh emas) + `HASH_SALT`, `NVD_API_KEY`, `GITHUB_TOKEN`, `PRODUCTHUNT_TOKEN`, `HTTP_TIMEOUT`.
- [ ] `CLAUDE.md` — uslub, papkalar, buyruqlar (`make check`), test tartibi, xavfsizlik qoidalari.
- [ ] Commit `chore: stage 0 — project skeleton and plan`.

## Bosqich 1 — Skelet

### Task 1: Config va xavfsizlik yordamchilari

**Files:** `app/config.py`, `app/utils/security.py`, `app/logging_setup.py`; Test: `tests/test_config.py`, `tests/test_security.py`

**Interfaces — Produces:**
- `class Settings(BaseSettings)` (`env_ignore_empty=True`); maydonlar `.env.example` bilan bir xil; `admin_ids: list[int]` vergul bilan; xususiyatlar `target_chat_id -> int | None` (dry_run → test_channel_id), `sync_database_url -> str`, `data_path -> Path`.
- `get_settings() -> Settings` (lru_cache).
- `hash_user_id(user_id: int, salt: str) -> str` (HMAC-SHA256 hex[:32]); `mask_secrets(text: str) -> str` (bot token, `sk-`, `sk-ant-`, `AIza`, `r8_`, `Key ` naqshlari → `***`).
- `setup_logging(level: str, log_dir: Path) -> None` (loguru, rotation 10 MB, retention 90 days, mask filter).

- [ ] Testlar: `test_empty_values_become_none` (`CHANNEL_ID=""` → None), `test_admin_ids_csv` (`"1, 2"` → `[1, 2]`), `test_target_chat_dry_run` (dry_run=True → test id, hech qachon channel_id), `test_sync_url` (`sqlite+aiosqlite:///data/bot.db` → `sqlite:///data/bot.db`), `test_hash_stable_and_salted`, `test_mask_bot_token` (`123456789:AA...35 belgi` → `***`).
- [ ] Implement → pass.

### Task 2: DB modellari, sessiya, repo, Alembic, holatlar mashinasi

**Files:** `app/db/models.py`, `app/db/session.py`, `app/db/repo.py`, `app/pipeline/state.py`, `alembic/env.py`, `alembic.ini`, `alembic/versions/0001_initial.py`; Test: `tests/test_state.py`, `tests/test_repo.py`

**Interfaces — Produces:**
- Jadvallar SPEC 10-bo'limdagidek + qo'shimcha maydonlar: `posts.needs_approval: bool`, `posts.approval_reason`, `posts.attempts`, `posts.discussion_message_id`, `posts.image_prompt`, `posts.title_short`, `posts.hashtags(json)`, `posts.slot`, `posts.extra(json)`; `stories.scored_at`, `stories.why_uz`, `stories.risk_flags(json)`, `stories.urls(json)`; `polls.closes_at`; `sources.last_error`.
- `PostStatus(StrEnum)`: NEW, SELECTED, DRAFTED, CHECKED, PENDING_APPROVAL, SCHEDULED, PUBLISHING, PUBLISHED, REJECTED, FAILED, EXPIRED. `PostKind(StrEnum)`: news, alert, tool, site, tip, poll, quiz, digest, qa.
- `can_transition(a, b) -> bool`; `async transition(session, post, new: PostStatus, actor: str, **details) -> None` (`InvalidTransition`, `audit_log` yozadi).
- `create_engine(url) -> AsyncEngine` (sqlite: WAL, foreign_keys, StaticPool for `:memory:`), `make_sessionmaker(engine)`, `async create_all(engine)` (testlar), `run_migrations(url)` (alembic upgrade head, thread ichida).
- `Repo(sessionmaker)`: `get_setting(key, default)`, `set_setting(key, value)`, `audit(actor, action, **details)`, `record_usage(...)`, `spent_today(tz) -> float`, `usage_breakdown(days)`, `get_post(id)`, `posts_by_status(*statuses)`, `cleanup_old(days=90)`.

- [ ] Testlar: `test_happy_path_transitions` (NEW→…→PUBLISHED), `test_fix_loop_allowed` (CHECKED→DRAFTED), `test_terminal_states_locked` (PUBLISHED→SCHEDULED rad), `test_any_to_failed_rejected_expired`, `test_transition_writes_audit`, `test_settings_roundtrip`, `test_spent_today_tashkent_day`, `test_cleanup_old_qa_and_moderation`.
- [ ] Alembic: `alembic revision --autogenerate -m initial` → `0001_initial.py`; `alembic upgrade head` toza bazada o'tadi.

### Task 3: Kontent formatlash va limitlar

**Files:** `app/content/formatting.py`, `limits.py`, `templates.py`, `hashtags.py`; Test: `tests/test_formatting.py`, `tests/test_limits.py`

**Interfaces — Produces:**
- `sanitize_html(html) -> str` (faqat b,strong,i,em,u,s,a[href],code,pre,blockquote,tg-spoiler; `<br>`→`\n`; boshqasi escape), `escape(text)`, `visible_length(html) -> int` (UTF-16 birliklarda, teglarsiz, entity'lar ochilgan), `extract_links(html) -> list[str]`, `normalize_uz(text) -> str` (o'/g' variantlari → oʻ/gʻ; inglizcha `'s` egalik qo'shimchasiga tegmaydi; faqat matn tugunlarida), `strip_code_fences(text) -> str`, `wrap_external(tag, text) -> str` (`</tag>` ni neytrallaydi), `truncate_visible(html, limit) -> str`.
- `limits.py`: `CAPTION_LIMIT=1024, MESSAGE_LIMIT=4096, POLL_QUESTION_LIMIT=300, POLL_OPTION_LIMIT=100, QUIZ_EXPLANATION_LIMIT=200, POLL_MIN_OPTIONS=2, POLL_MAX_OPTIONS=12, POST_MIN=500, POST_MAX=900, TITLE_SHORT_LIMIT=60, QA_ANSWER_LIMIT=700`; `validate_poll(question, options) -> list[str]`, `validate_quiz(question, options, correct_index, explanation) -> list[str]`.
- `templates.py`: `TEMPLATES: dict[PostKind, str]` (SPEC 5-bo'lim shablonlari + site, tip, digest, qa), `KIND_EMOJI`, `render_footer(username) -> str`.
- `hashtags.py`: `DEFAULT_HASHTAGS: dict[PostKind, list[str]]`, `normalize_hashtags(tags, kind) -> list[str]` (ʻ/'/bo'shliq olib tashlanadi, `#` qo'shiladi, dublikatlarsiz, ≤ 4).

- [ ] Testlar: `test_sanitize_drops_script_keeps_b`, `test_visible_length_emoji_utf16` (`"😀"` → 2), `test_visible_length_ignores_tags_and_entities` (`"<b>a&amp;b</b>"` → 3), `test_normalize_uz` (`"o'zbek g'oya"` → `"oʻzbek gʻoya"`, `"Google's"` o'zgarmaydi, `href` ichiga tegmaydi), `test_wrap_external_neutralizes_closing_tag`, `test_quiz_limits` (301 belgili savol → xato; 3 variant → xato; correct_index 4 → xato), `test_poll_limits` (13 variant → xato), `test_hashtags_normalize` (`"so'rovnoma"` → `"#sorovnoma"`).

### Task 4: AI qatlami — provayderlar, router, budjet

**Files:** `app/ai/types.py`, `pricing.py`, `schemas.py`, `prompts.py`, `prompts/*.md`, `providers/*.py`, `images/*.py`, `router.py`, `app/utils/budget.py`; Test: `tests/test_ai_router.py`, `tests/test_providers.py`, `tests/test_budget.py`

**Interfaces — Produces:**
- `Message(role: Literal["system","user","assistant"], content: str, images: list[bytes] = [], cache: bool = False)`; `LLMResult(text, parsed: BaseModel | None, input_tokens, output_tokens, cached_tokens, model, provider, role, fallback_used: bool)`.
- `LLMClient` protokoli: `provider: str`, `model: str`, `async complete(messages, *, json_mode: bool, temperature: float, max_tokens: int) -> RawCompletion(text, input_tokens, output_tokens, cached_tokens)`, `async list_models() -> list[str] | None`. `ImageClient`: `provider`, `model`, `async generate(prompt, *, size="1024x1024") -> bytes`.
- Provayderlar: `OpenAIClient(api_key, model, base_url=None)` (chat.completions; `temperature` rad etilsa usiz qayta yuboradi va eslab qoladi; `max_completion_tokens`), `OpenAICompatClient` (`max_tokens`), `AnthropicClient` (system bloki `cache_control`), `GeminiClient` (google-genai `client.aio.models.generate_content`, `response_mime_type="application/json"`). Rasmlar: `OpenAIImageClient`, `GeminiImageClient` (imagen → `generate_images`, aks holda `generate_content` inline_data), `StabilityImageClient`, `ReplicateImageClient`, `FalImageClient` (httpx).
- `build_clients(settings) -> Clients(writer, editor, fast, image)` (`providers/factory.py`).
- `cost_usd(model, input_tokens, output_tokens, cached_tokens, prices) -> float`; `DEFAULT_PRICES` (gpt-6-sol 2/10, gpt-6-luna 0.10/0.50, keshli kirish 0.20/0.01, rasm narxi — har bir rasm uchun) `MODEL_PRICES_JSON` bilan almashtiriladi.
- `BudgetGuard(repo, daily_budget, notifier)`: `async state() -> Literal["ok","warn","exceeded"]`, `async ensure(essential: bool)` → `BudgetExceeded`; 80% da kuniga bir marta ogohlantirish.
- `AIRouter(clients, repo, budget, *, timeout=90, attempts=3)`: `async complete(role: Literal["writer","editor","fast"], messages, *, schema: type[T] | None = None, temperature=0.4, max_tokens=1500, essential=True) -> LLMResult`; fallback: writer→editor, editor→writer (`fallback_used=True`), fast→writer; `async image(prompt, size) -> bytes | None`; `async check_models() -> list[str]` (muammolar ro'yxati).
- `load_prompt(name, **vars) -> str` (`{{var}}` almashtirish).

- [ ] Testlar: `test_json_parse_with_code_fence`, `test_schema_mismatch_retries_once_then_raises`, `test_retry_three_times_then_fallback_writer_to_editor`, `test_editor_fallback_marks_fallback_used`, `test_usage_recorded_with_cost` (gpt-6-sol 1M kirish → $2), `test_budget_exceeded_blocks_non_essential`, `test_budget_warn_once_per_day`, `test_openai_client_retries_without_temperature` (respx: 400 "temperature" → ikkinchi so'rovda temperature yo'q), `test_anthropic_client_parses_usage` (respx), `test_gemini_client_parses_text` (respx), `test_openai_image_b64` (respx).

### Task 5: Bot asosi — sender, notifier, admin filtri, /start /status /post /id

**Files:** `app/bot/sender.py`, `notify.py`, `middlewares.py`, `keyboards.py`, `handlers/admin.py`, `setup.py`, `app/context.py`, `app/main.py`, `app/__main__.py`; Test: `tests/test_sender.py`, `tests/test_notify.py`, `tests/test_admin_handlers.py`

**Interfaces — Produces:**
- `TelegramSender` protokoli: `send_message(chat_id, text, *, reply_markup=None, reply_to=None, direct_topic_id=None) -> int`, `send_photo(chat_id, photo: bytes, caption: str | None, *, reply_markup=None) -> int`, `send_poll(chat_id, *, question, options, quiz: bool, correct_option_id, explanation, is_anonymous=True) -> tuple[int, str]`, `stop_poll(chat_id, message_id) -> dict`, `member_count(chat_id) -> int`, `delete_message(chat_id, message_id)`, `restrict(chat_id, user_id, until)`, `ban(chat_id, user_id)`, `create_invite_link(chat_id, name) -> str`. `AiogramSender(bot)` — chatga 1 msg/s, `TelegramRetryAfter` → kutib qayta (3 marta).
- `AdminNotifier(sender, admin_ids)`: `async notify(text, *, key: str | None = None)` — bir xil `key` soatiga ≤ 1.
- `AdminFilter` / `is_admin(user_id)`; `AppContext` dataclass (settings, repo, router, sender, notifier, services) + `set_ctx/get_ctx`.

- [ ] Testlar: `test_sender_respects_retry_after` (soxta bot birinchi chaqiruvda RetryAfter(2)), `test_sender_one_per_second_per_chat`, `test_notifier_throttles_same_key`, `test_non_admin_cannot_use_admin_command`, `test_status_text_contains_spend_and_queue`.
- [ ] `/post <mavzu|havola>` — Task 10 orkestratoriga ulanadi (Bosqich 1 da: havola bo'lsa matnni oladi, yozuvchi → tekshiruvchi → adminga qoralama).
- [ ] Commit `feat: stage 1 — skeleton (config, db, ai router, bot core)`.

## Bosqich 2 — Kontent quvuri

### Task 6: Publisher va kompozitsiya

**Files:** `app/pipeline/compose.py`, `publish.py`; Test: `tests/test_publish.py`

**Interfaces — Produces:**
- `OutboundMessage(kind: Literal["photo","text","poll"], text, photo: bytes | None, poll: dict | None)`; `compose(post, image_bytes) -> list[OutboundMessage]` (rasm + caption ≤ 1024; uzunroq → rasm (sarlavha caption) + matn; rasmsiz → matn ≤ 4096).
- `Publisher(repo, sender, settings, notifier)`: `async publish(post_id) -> bool` (SCHEDULED→PUBLISHING→PUBLISHED; `message_id`, `published_at`; xatoda `attempts+1`, 3 dan keyin FAILED + admin), `async recover_inflight() -> int`, `async publish_due(now) -> int`.

- [ ] Testlar: `test_dry_run_targets_test_channel`, `test_publish_idempotent_second_call_noop`, `test_recover_publishing_with_message_id_marks_published`, `test_recover_publishing_without_message_id_fails_and_notifies`, `test_long_text_splits_photo_and_message`, `test_failure_three_attempts_then_failed`.

### Task 7: Yig'uvchilar

**Files:** `app/collectors/base.py`, `normalize.py`, `rss.py`, `cisa_kev.py`, `nvd.py`, `hackernews.py`, `github.py`, `extract.py`, `dedupe.py`, `service.py`, `seed.py`, `app/utils/http.py`; Test: `tests/test_normalize.py`, `tests/test_dedupe.py`, `tests/test_collectors.py`

**Interfaces — Produces:**
- `RawItem(url, title, summary, published_at: datetime | None, lang, extra: dict)`; har modulda `async fetch(http, source) -> list[RawItem]`; `FETCHERS: dict[str, Callable]` (`rss`, `cisa_kev`, `nvd`, `hackernews`, `github`).
- `canonical_url(url) -> str` (utm_*, fbclid, gclid, yclid, mc_cid, mc_eid, ref, ref_src, igshid olib tashlanadi; host kichik harf; fragment yo'q; query tartiblangan; oxirgi `/` yo'q), `url_hash(url) -> str`.
- `title_similarity(a, b) -> float` (rapidfuzz `token_sort_ratio`, normallashtirilgan), `SIMILARITY_THRESHOLD=85`, `STORY_WINDOW=timedelta(hours=48)`; `async attach_to_story(session, article) -> Story`.
- `CollectorService(repo, http, notifier)`: `async run_once() -> CollectStats(new_articles, new_stories, failed_sources)`; 3 ketma-ket xato → manba o'chiriladi + adminga xabar.
- `async extract_text(http, url) -> str | None` (trafilatura, thread ichida, 30k belgigacha).
- `seed_sources(repo)` — Ilova jadvalidagi manbalar (tekshirilgan URL'lar bilan).

- [ ] Testlar: `test_canonical_strips_tracking`, `test_same_url_same_hash`, `test_similar_titles_merge_into_story` (≥85 → bitta story, `article_count=2`), `test_old_story_outside_48h_not_merged`, `test_rss_parse_fixture`, `test_cisa_kev_recent_only`, `test_hn_filters_without_url`, `test_source_disabled_after_three_failures`, `test_existing_url_not_reinserted`.

### Task 8: Saralovchi va jadval mantig'i

**Files:** `app/pipeline/select.py`, `app/content/schedule.py`, `app/utils/timeutil.py`; Test: `tests/test_select.py`, `tests/test_schedule.py`

**Interfaces — Produces:**
- `SlotSpec(name, time: time, kinds: list[PostKind])`; `DEFAULT_SLOTS` (08:30 news/alert, 13:00 tool/site/tip, 19:30 news/poll/quiz), `slot_kind(slot_name, weekday) -> PostKind` (13:00: Du tool, Se site, Ch tip, Pa tool, Ju site, Sh tool, Ya tip; 19:30: Du news, Se poll, Ch quiz, Pa news, Ju poll, Sh quiz, Ya news).
- `now_tz()`, `in_quiet_hours(dt, start=23:00, end=07:00) -> bool`, `shift_out_of_quiet(dt, resume=07:30) -> datetime`, `day_bounds(dt) -> (start, end)`.
- `Selector(repo, router)`: `async score_new(limit=30, only_category=None) -> int` (luna filtr → sol baho; har story bir marta), `async pick(kind, now) -> Story | None` (24 soat, kategoriya kuniga ≤ 2, 7 kunlik mavzu takrorlanmaydi, ball ≥ 50), `async breaking_candidates(now) -> list[Story]` (`is_breaking` va ball ≥ 85).

- [ ] Testlar: `test_slot_rotation_weekly_quotas` (haftada tool 3, site 2, tip 2, poll 2, quiz 2), `test_quiet_hours_shift_to_0730`, `test_quiet_hours_boundaries` (22:59 emas, 23:00 ha, 06:59 ha, 07:00 emas), `test_score_each_story_once`, `test_pick_respects_category_daily_cap`, `test_pick_skips_topic_covered_last_7_days`, `test_irrelevant_filtered_by_fast_model`.

### Task 9: Yozuvchi va tekshiruvchi

**Files:** `app/pipeline/write.py`, `check.py`, `links.py`; Test: `tests/test_write_check.py`, `tests/test_links.py`

**Interfaces — Produces:**
- `Writer(router, settings)`: `async write(kind, *, source_text, story_title, source_urls, instructions=None, previous=None, issues=None) -> WriterOutput` (normalize_uz, sanitize_html, footer, hashtag, title_short ≤ 60).
- `Checker(router, http)`: `async check(draft_html, *, source_text, kind, allowed_domains, has_image) -> CheckReport(verdict, issues, code_issues, needs_approval, approval_reason, degraded)`; kod tekshiruvlari: uzunlik, manba havolasi (tip/poll/quiz dan tashqari), domen ruxsati, havola tirikligi; O'zbekiston tashkiloti "buzildi" → needs_approval.
- `links.py`: `allowed_domains(urls) -> set[str]`, `domain_allowed(url, allowed) -> bool` (subdomenlar ham), `async link_alive(http, url) -> bool` (HEAD → GET, redirect, 200).

- [ ] Testlar: `test_invented_url_rejected`, `test_missing_source_link_is_issue_for_news`, `test_fix_loop_max_two_then_approval`, `test_reject_verdict_rejects_story`, `test_degraded_checker_forces_approval`, `test_uz_org_breach_forces_approval`, `test_link_alive_follows_redirect` (respx 301→200).

### Task 10: Orkestrator va /post

**Files:** `app/pipeline/orchestrator.py`; Test: `tests/test_orchestrator.py`

**Interfaces — Produces:**
- `Pipeline(ctx)`: `async prepare_slot(slot_name, scheduled_at) -> int | None`, `async prepare_from_story(story, kind, scheduled_at, *, force_approval=False) -> int | None`, `async prepare_from_admin(topic_or_url) -> int | None`, `async prepare_tip(scheduled_at)`, `async after_check(post)` (`auto`: needs_approval bo'lmasa SCHEDULED; `semi_auto`/`manual`: PENDING_APPROVAL + adminga), `async rewrite(post_id, instruction)`, `async replace_text(post_id, html)`, `async regenerate_image(post_id)`, `async expire_stale(now)` (yangilik 6 soat → EXPIRED; 30 daqiqa timeout `approval_timeout_action=publish` bo'lsa SCHEDULED), `async handle_breaking(now)`.

- [ ] Testlar (FakeLLM + FakeSender bilan to'liq sikl): `test_full_cycle_semi_auto_reaches_pending_approval`, `test_full_cycle_auto_publishes_to_test_channel`, `test_news_expires_after_6h`, `test_tool_does_not_expire`, `test_breaking_max_one_per_day_and_quiet_hours`, `test_source_injection_kept_inside_tags`.

### Task 11: Tasdiqlash oynasi va scheduler

**Files:** `app/bot/handlers/approval.py`, `app/bot/keyboards.py`, `app/scheduler/jobs.py`, `app/scheduler/setup.py`; Test: `tests/test_approval.py`, `tests/test_jobs.py`

**Interfaces — Produces:**
- `ApprovalCB(CallbackData, prefix="ap")`: `action: Literal["pub","sched","edit","rewrite","img","rej","ban"]`, `post_id: int`; `send_for_approval(ctx, post_id)`; `EditState` FSM (≥ 300 belgi yoki `<b>` bor → tayyor matn, aks holda ko'rsatma).
- `jobs.py` — modul darajasidagi async funksiyalar (`collect_job`, `score_job`, `slot_job(slot_name)`, `publish_due_job`, `expire_job`, `snapshot_job`, `daily_report_job`, `weekly_report_job`, `digest_job`, `poll_close_job`, `backup_job`, `cleanup_job`, `heartbeat_job`, `qa_faq_job`); `setup_scheduler(ctx) -> AsyncIOScheduler` (SQLAlchemyJobStore, `replace_existing=True`, `coalesce=True`, `misfire_grace_time=900`, slot tayyorlash slotdan 45 daqiqa oldin).

- [ ] Testlar: `test_callback_from_non_admin_ignored`, `test_callback_on_wrong_state_answers_error`, `test_publish_button_schedules_now`, `test_reject_button_rejects`, `test_scheduler_registers_all_jobs` (job id'lar ro'yxati), `test_slot_prepare_time_is_45_min_before`.
- [ ] Commit `feat: stage 2 — content pipeline, scheduler, approval`.

## Bosqich 3 — Rasmlar

### Task 12: Pillow brend shabloni va rasm bosqichi

**Files:** `app/content/brand_image.py`, `app/pipeline/image.py`, `assets/fonts/*.ttf`, `assets/fonts/OFL.txt`; Test: `tests/test_brand_image.py`, `tests/test_image_stage.py`

**Interfaces — Produces:**
- `BRAND = {"navy": "#0B1F3A", "cyan": "#00C2FF", "white": "#FFFFFF"}`; `render_cover(base: bytes | None, *, title: str, category: str, username: str, size=(1080, 1080)) -> bytes` (pastki 1/3 gradient, sarlavha ≤ 60 qatorlarga bo'linadi, kategoriya belgisi, suv belgisi; `base=None` → brend foni).
- `ImageStage(router, settings, repo)`: `async make(post, *, title, category, prompt) -> bytes | None` (2-model → Pillow; xato → brend fon; u ham xato → None; ixtiyoriy vision tekshiruv → 1 qayta generatsiya); `data/images/<post_id>.png` ga saqlaydi.

- [ ] Testlar: `test_render_cover_png_size`, `test_font_has_uz_glyphs` (ʻ U+02BB glif mavjud), `test_long_title_wraps_not_overflow`, `test_image_provider_failure_falls_back_to_brand`, `test_vision_reject_triggers_one_regeneration`.
- [ ] Commit `feat: stage 3 — images`.

## Bosqich 4 — Interaktiv

### Task 13: So'rovnoma va test

**Files:** `app/interactive/polls.py`, `quizzes.py`; Test: `tests/test_polls_quizzes.py`

**Interfaces — Produces:**
- `PollService(ctx)`: `async create(topic: str | None, purpose: Literal["fun","research"]) -> int | None`, `async on_poll_update(poll_id, options_results)`, `async close_due(now) -> int` (24 soat fun, 48 soat research), `research_context() -> str` (saralovchiga).
- `QuizService(ctx)`: `async create(topic: str | None, level: str | None) -> int | None` — `validate_quiz`, `quiz_verify` (javobsiz, aralashtirilgan variantlar); mos kelmasa / `ambiguous` / `confidence < 0.7` → tashlanadi (2 urinish).
- `QUIZ_TOPICS`, `POLL_TOPICS` ro'yxatlari.

- [ ] Testlar: `test_quiz_verified_matches`, `test_quiz_dropped_on_mismatch`, `test_quiz_dropped_on_ambiguous`, `test_quiz_limits_enforced`, `test_poll_always_anonymous`, `test_poll_closed_after_24h`, `test_poll_results_saved`.

### Task 14: Savol-javob va moderatsiya

**Files:** `app/interactive/qa.py`, `moderation.py`, `ratelimit.py`, `app/bot/handlers/qa.py`, `group.py`; Test: `tests/test_qa.py`, `tests/test_moderation.py`

**Interfaces — Produces:**
- `RateLimiter(per_minute=3, per_day=20)`: `check(user_key, now) -> Literal["ok","minute","day"]`.
- `QAService(ctx)`: `async answer(user_id, text, channel: Literal["dm","comments","channel_dm"]) -> str` (rate limit, budjet `essential=False`, sezgir ma'lumot (karta/SMS kod) ogohlantirishi, `<user>` teg, ≤ 700, `qa_logs`).
- `ModerationService(ctx)`: `async handle(chat_id, message_id, user_id, text, *, is_new_member_first_msg) -> ModerationAction` (havola + yangi a'zo → delete; luna label; `ok` dan boshqa → delete; 2-marta → ogohlantirish xabari; 3-marta (7 kun ichida) → 24 soat mute; ban → admin tugmasi), `async daily_summary(day) -> str`.

- [ ] Testlar: `test_rate_limit_3_per_minute`, `test_rate_limit_20_per_day`, `test_card_number_triggers_warning_without_llm`, `test_answer_truncated_to_700`, `test_budget_exceeded_qa_paused_message`, `test_new_member_link_deleted_without_llm`, `test_escalation_delete_warn_mute`, `test_uncertain_label_is_ok`.
- [ ] Commit `feat: stage 4 — polls, quizzes, Q&A, moderation`.

## Bosqich 5 — Analitika va o'sish

### Task 15: Metrikalar, invite-linklar, hisobotlar, /growth, /ask

**Files:** `app/analytics/metrics.py`, `invites.py`, `reports.py`, `growth.py`, `app/bot/handlers/updates.py`; Test: `tests/test_analytics.py`

**Interfaces — Produces:**
- `engagement_score(reactions, comments, poll_votes, subscribers) -> float` = `(r + 2c + v) / subs * 1000` (subs=0 → 0).
- `MetricsService(ctx)`: `async snapshot()`, `async on_reaction_count(chat_id, message_id, reactions)`, `async on_comment(discussion_message_id)`, `async on_auto_forward(channel_message_id, discussion_message_id)`.
- `InviteService(ctx)`: `async create(name) -> str`, `async on_member_update(user_id, old_status, new_status, invite_link_url)` (join/leave, user_hash, havolaga bog'lash), `async stats() -> list[dict]` (joins, leaves, 7 kundan keyin qolganlar).
- `ReportService(ctx)`: `async daily(day) -> str`, `async weekly() -> str`, `async stats(days) -> dict`, `best_times(stats) -> list` (≥ 14 kun ma'lumot bo'lsa).
- `GrowthService(ctx)`: `async growth_report(days=7) -> str`, `async ask(question) -> str`.

- [ ] Testlar: `test_engagement_formula` (r=10,c=5,v=20,subs=1000 → 40.0), `test_join_via_named_link_counted`, `test_leave_attributed_to_link`, `test_daily_report_contains_numbers`, `test_growth_prompt_has_stats_json_and_no_fake_followers_rule`, `test_reaction_update_stored`.
- [ ] Commit `feat: stage 5 — analytics and growth`.

## Bosqich 6 — Mustahkamlash va deploy

### Task 16: Backup, heartbeat, Docker, README, manbalarni tekshirish

**Files:** `app/utils/backup.py`, `heartbeat.py`, `Dockerfile`, `docker-compose.yml`, `README.md`, `scripts/check_sources.py`; Test: `tests/test_backup.py`

**Interfaces — Produces:**
- `async backup_sqlite(db_path, backup_dir, keep_days=7) -> Path` (sqlite `backup()` API), `prune_backups(dir, keep_days)`; `touch_heartbeat(path)`, `heartbeat_age(path) -> float`.
- Dockerfile (python:3.12-slim, non-root, `HEALTHCHECK` heartbeat ≤ 600 s); compose: `bot` servisi, `./data:/app/data`, `restart: unless-stopped`, `TZ=Asia/Tashkent`, `env_file: .env`.
- `scripts/check_sources.py` — har manba URL'ini so'raydi va holatini chiqaradi.

- [ ] Testlar: `test_backup_creates_file_and_prunes_old`, `test_heartbeat_age`.
- [ ] `make check` (ruff + mypy + pytest) toza o'tadi.
- [ ] Commit `feat: stage 6 — hardening and deploy`.

## Bosqich 7 — ixtiyoriy (qurilmaydi)

Telethon ko'rishlar statistikasi va webhook — alohida kelishiladi.
