# MongoDB va v2 funksiyalar — amalga oshirish rejasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maʼlumotlar bazasini SQLite/SQLAlchemy dan MongoDB (Atlas) ga koʻchirish; soʻng v2: qoʻlda media-post va rejalashtirish, checkbox sozlamalar, rasm qidirish (Pexels/Wikimedia) + AI rasm uchun admin ruxsati, "Ulashish" tugmasi.

**Architecture:** `app/db/models.py` — dataclass hujjatlar (maydon nomlari oʻzgarmaydi, `id` → `_id`, butun son, `counters` kolleksiyasidan). `app/db/repo.py` — `Repo` va umumiy `Collection[T]` (insert/get/find/find_one/count/save/update/cas/update_where/delete_where). Session tushunchasi yoʻq: `transition(repo, post, new, actor)` statusni xotirada oʻzgartiradi va auditni yozadi, chaqiruvchi `save()` qiladi. Nashr `cas()` bilan atomik.

**Tech Stack:** pymongo ≥ 4.10 (`AsyncMongoClient`, `tz_aware=True`), APScheduler `MongoDBJobStore`, testlarda mongomock (async adapter `tests/mongo_fake.py`).

**Spec:** `SPEC.md` + foydalanuvchi talablari (2026-11-06 chat): MongoDB; rasm qidirish arxitekturasi; checkbox sozlamalar; qoʻlda post.

## Global Constraints

- Bot faqat `MONGODB_DB` (standart `it_dunyosi_bot`) bazasidan foydalanadi; URI dagi boshqa bazalarga tegmaydi.
- Barcha vaqtlar UTC da saqlanadi va aware `datetime` boʻlib qaytadi.
- Maqola/"rasmiy manba" rasmlari olinmaydi (mualliflik huquqi); faqat Pexels litsenziyasi, Wikimedia da CC0/PD/CC BY/CC BY-SA (NC/ND yoʻq).
- Rasm topilmasa AI rasm faqat admin ruxsati bilan.
- Commitlarda `Co-Authored-By` yoʻq (foydalanuvchi talabi).

## Review Focus

1. **Bir post ikki marta chiqmasligi** — tugma va `publish_due` bir vaqtda → faqat bittasi `cas()` dan oʻtadi → M2 testi.
2. **Naive/aware datetime aralashuvi** — filtrlardagi aware vaqtlar mongomock va Atlas da bir xil ishlashi → M1 testi.
3. **Takroriy URL** — `articles.url_hash` unique indeks, takror insert yiqitmaydi → M1/M2 testi.
4. **Rasm topilmagan post auto rejimda** — oʻzi chiqmaydi, ruxsat soʻraydi → V3 testi.
5. **Qoʻlda post uzun caption bilan** (>1024) — media + alohida matn → V1 testi.

---

### Task M1: Mongo maʼlumot qatlami
Files: `app/db/models.py` (dataclass), `app/db/repo.py` (`Repo`, `Collection`), `app/db/mongo.py` (`connect(uri, db_name)`, `ensure_indexes(db)`), `app/pipeline/state.py` (`transition(repo, post, new, actor, **details)`), `tests/mongo_fake.py`, `tests/conftest.py`; Test: `tests/test_state.py`, `tests/test_repo.py`.
- Testlar: mavjud holat/repo testlari yangi API bilan + `test_ids_autoincrement`, `test_datetime_roundtrip_aware_utc`, `test_filter_with_aware_datetime`, `test_cas_only_one_wins`.

### Task M2: Modullarni koʻchirish
publisher, collectors, selector, orchestrator, approval/admin handlers, interactive, analytics, image, backup (JSONL.gz eksport), scheduler (`MongoDBJobStore`), main (`MONGODB_URI` majburiy, indekslar), config (`mongodb_uri`, `mongodb_db`; `database_url` olib tashlanadi), scripts. Alembic/SQLAlchemy olib tashlanadi.
- Testlar: mavjud 329 test yangi API bilan yashil; `test_publish_cas_prevents_double_send`; `test_backup_exports_collections`.

### Task M3: Atlas integratsion tekshiruvi
`scripts/check_mongo.py` — ulanish, indekslar, yozish/oʻqish, vaqt zonasi; `it_dunyosi_bot_test` bazasida real yigʻish sikli, soʻng baza oʻchiriladi.

### Task V1: Qoʻlda post (matn / rasm / video) va rejalashtirish
`app/bot/handlers/manual.py`, `PostKind.MANUAL`, `extra.media = {type, file_id}`; sender: `send_media(chat, type, file_id, caption)`; tugmalar: Hozir / keyingi slotlar / boshqa vaqt / bekor.
- Testlar: `test_photo_from_admin_starts_manual_post`, `test_manual_post_scheduled_and_published_with_file_id`, `test_long_caption_split`.

### Task V2: Checkbox sozlamalar
Runtime: `slot_times` (roʻyxat), `categories`, `polls_per_week`, `quizzes_per_week`; `plan_day(weekday, times, cats, polls, quizzes) -> list[PostKind]` (standart sozlamada eski jadval bilan bir xil); `/settings` inline checkbox menyu; vaqtlar oʻzgarsa scheduler qayta quriladi.
- Testlar: `test_plan_day_default_matches_old_rotation`, `test_plan_day_respects_categories_and_quotas`, `test_settings_toggle_time_and_category`.

### Task V3: Rasm qidirish + ruxsat
`app/images/search.py` (Pexels, Wikimedia, litsenziya/sifat tekshiruvi), writer chiqishiga `image_query_en`; `image_mode` = `search_then_ask` (standart) | `ai` | `none`; topilmasa post tasdiqqa keladi: 🎨 AI rasm / 📝 Rasmsiz / ❌.
- Testlar: `test_pexels_result_used_and_credited`, `test_wikimedia_nc_license_rejected`, `test_no_image_found_asks_admin_even_in_auto`, `test_ai_image_button_generates_and_schedules`.

### Task V4: "Ulashish" tugmasi
Nashrdan keyin `edit_reply_markup` bilan `📤 Ulashish` (t.me/share/url…); runtime `share_button`.
- Testlar: `test_share_button_added_after_publish`.
