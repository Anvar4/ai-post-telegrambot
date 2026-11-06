# IT Dunyosi AI bot

"IT Dunyosi" Telegram kanali uchun sunʼiy intellekt boshqaradigan administrator-bot. Bot IT, AI va kiberxavfsizlik yangiliklarini oʻzi topadi, oʻzbek tilida post yozadi, faktlarni tekshiradi, muqova rasmini chizadi va postlarni jadval boʻyicha chiqaradi. Bundan tashqari soʻrovnoma va testlar oʻtkazadi, obunachilarning savollariga javob beradi, izohlarni moderatsiya qiladi hamda sizga kunlik va haftalik hisobot yuboradi.

> Toʻliq talablar `SPEC.md` da. Bu fayl botni sozlash va ishga tushirish boʻyicha qoʻllanma.

## Mundarija

1. [Qanday ishlaydi](#1-qanday-ishlaydi)
2. [Telegram sozlash](#2-telegram-sozlash)
3. [`.env` faylini toʻldirish](#3-env-faylini-toldirish)
4. [Tekshirish skriptlari](#4-tekshirish-skriptlari)
5. [Kompyuterda ishga tushirish](#5-kompyuterda-ishga-tushirish)
6. [Serverga oʻrnatish (Docker)](#6-serverga-ornatish-docker)
7. [Kundalik ishlatish](#7-kundalik-ishlatish)
8. [Test rejimidan jonli rejimga oʻtish](#8-test-rejimidan-jonli-rejimga-otish)
9. [Xarajat va budjet](#9-xarajat-va-budjet)
10. [Xavfsizlik](#10-xavfsizlik)
11. [Muammolarni hal qilish](#11-muammolarni-hal-qilish)
12. [Dasturchilar uchun](#12-dasturchilar-uchun)

---

## 1. Qanday ishlaydi

```
Manbalar (RSS, CISA KEV, NVD, Hacker News, GitHub, UZCERT…) ── har 30 daqiqada
   → dublikatlar birlashtiriladi (bitta voqea = bitta "story")
   → gpt-6-luna: mavzuga oidmi?  → gpt-6-sol: 0–100 ball, kategoriya, shoshilinchmi?
   → 1-model (yozuvchi): oʻzbekcha post
   → gpt-6-sol: fakt-tekshiruv (kerak boʻlsa 2 martagacha tuzatish)
   → rasm: Pexels / Wikimedia dan bepul rasm (litsenziya va sifat tekshiruvi) + brend shabloni;
     topilmasa — sizdan soʻraydi: 🎨 AI rasm (pullik) / 📝 rasmsiz / ❌
   → semi_auto: qoralama sizga tugmalar bilan keladi | auto: oʻzi chiqadi
   → nashrdan keyin postga "📤 Ulashish" tugmasi qoʻshiladi
```

| Kalit | Roli | Vazifasi |
|---|---|---|
| 1-kalit (`LLM_MAIN_*`) | Yozuvchi | Postlar, soʻrovnoma va testlar, obunachilarga javoblar |
| 2-kalit (`IMAGE_*`) | Dizayner | Bepul rasm topilmaganda (faqat sizning ruxsatingiz bilan) matnsiz muqova rasmi |
| 3-kalit (`OPENAI_API_KEY`) | Bosh muharrir | `gpt-6-sol`: saralash, fakt-tekshiruv, oʻsish tahlili, `/ask`. `gpt-6-luna`: tez filtr va moderatsiya |

Bitta model ishlamay qolsa, bot toʻxtamaydi: yozuvchi oʻrnini `gpt-6-sol` bosadi, rasm oʻrniga brend fon chiziladi, tekshiruvchi ishlamasa post albatta sizning tasdigʻingizga keladi.

**Standart jadval** (Toshkent vaqti). Hammasi `/settings` menyusida katakchalar bilan oʻzgaradi: kuniga nechta post (1–8), soat nechida, qaysi turkumlar (kiber, IT yangiliklar, AI, ilovalar, saytlar, maslahatlar) va haftasiga nechta soʻrovnoma/test (0–7).

| Vaqt | Nima chiqadi |
|---|---|
| 08:30 | Asosiy yangilik yoki kiber ogohlantirish |
| 13:00 | Ilova (haftasiga 3) / sayt (2) / maslahat (2) |
| 19:30 | Yangilik, soʻrovnoma (haftasiga 2) yoki test (haftasiga 2) |
| Yakshanba 20:00 | Haftalik dayjest |
| Istalgan vaqt | Shoshilinch kiber xabar (kuniga koʻpi bilan 1 ta; 23:00–07:00 oraligʻida 07:30 ga suriladi) |

Boshqa vaqtlar tanlansa ham tartib shu: kunning birinchi posti — yangilik, keyin navbat bilan yangilik va foydali post (ilova/sayt/maslahat), soʻrovnoma va test kunlarida ular kunning oxirgi postlari boʻladi. Oʻchirilgan turkum oʻrniga qolganlari ishlatiladi.

Qoralamalar slotdan 45 daqiqa oldin tayyorlanadi, ularni koʻrib chiqishga vaqtingiz qoladi.

---

## 2. Telegram sozlash

### 2.1. BotFather

1. [@BotFather](https://t.me/BotFather) → `/newbot` (yoki mavjud bot) → tokenni `.env` dagi `TELEGRAM_BOT_TOKEN` ga yozing.
2. `/setprivacy` → botni tanlang → **Disable**. Busiz bot izohlar guruhidagi xabarlarni oʻqiy olmaydi.
3. Xohlasangiz: `/setdescription`, `/setuserpic`.

### 2.2. Test kanal va test guruh (avval shular bilan sinaladi)

1. Yopiq **test kanal** yarating va botni unga **administrator** qiling. Kerakli huquqlar: *xabar joylash*, *boshqalarning xabarini tahrirlash*, *xabarlarni oʻchirish*, *havola orqali taklif qilish*. **"Yangi admin qoʻshish" huquqini bermang.**
2. Test kanalga **izohlar guruhini** ulang: Kanal → Tahrirlash → Muhokama (Discussion). Botni u guruhda ham admin qiling, huquqlari: *xabarlarni oʻchirish* va *aʼzolarni cheklash*.

> ⚠️ Oddiy guruh kanalga ulanganda **superguruhga** aylanadi va uning ID raqami oʻzgaradi (`-4…` → `-100…`). Shuning uchun ID ni ulangandan **keyin** oling.

### 2.3. Haqiqiy kanal

Botni haqiqiy kanalga ham xuddi shu huquqlar bilan admin qiling va izohlar guruhini ulang. Kanalda "Direct messages" yoqilgan boʻlsa, botga uni boshqarish huquqini ham bering: shunda bot kanal DM idagi savollarga ham javob beradi.

### 2.4. ID raqamlarni olish

- **Oʻz ID ingiz:** [@userinfobot](https://t.me/userinfobot) ga yozing. Olingan raqamni `ADMIN_IDS` ga qoʻying (bir nechta admin boʻlsa vergul bilan).
- **Guruh ID si:** bot ishga tushgach, guruhga `/id` yozing (buni `ADMIN_IDS` dagi akkaunt yozishi kerak).
- **Kanal ID si:** kanaldan istalgan postni [@userinfobot](https://t.me/userinfobot) ga forward qiling yoki botga shaxsiy chatda `/id` yozing. Kanal ID si `-100…` bilan boshlanadi.

Hammasi joyidaligini tekshirish uchun: `python scripts/check_telegram.py` (hech qanday xabar yubormaydi).

---

## 3. `.env` faylini toʻldirish

`.env.example` dan nusxa oling va **faqat `.env` ni** toʻldiring:

```bash
cp .env.example .env
```

> `.env.example` git ga tushadi, `.env` esa tushmaydi. Token va kalitlarni **hech qachon** `.env.example` ga yozmang.
> Har bir kalit faylda **bir marta** boʻlsin: bir kalit ikki marta yozilsa, oxirgisi ishlatiladi. Bot ishga tushganda bunday takrorlarni koʻrsatib beradi.

| Kalit | Nima yoziladi | Misol |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather bergan token | `123456:AA…` |
| `CHANNEL_ID` | Haqiqiy kanal ID si | `-1001234567890` |
| `CHANNEL_USERNAME` | Kanal username (suv belgisi va post oxiri uchun) | `@kanalingiz` |
| `TEST_CHANNEL_ID` | Test kanal ID si | `-100…` |
| `DISCUSSION_GROUP_ID` | Kanal izohlari guruhi (superguruh) ID si | `-100…` |
| `TEST_GROUP_ID` | Test guruh (ixtiyoriy) | `-100…` |
| `ADMIN_IDS` | Sizning Telegram ID ingiz | `123456789,987654321` |
| `PUBLISH_MODE` | `semi_auto` (tavsiya) / `auto` / `manual` | `semi_auto` |
| `DRY_RUN` | `true` boʻlsa hamma narsa **faqat test kanalga** ketadi | `true` |
| `LLM_MAIN_PROVIDER` | `deepseek` / `anthropic` / `openai` / `gemini` / `openai_compatible` | `deepseek` |
| `LLM_MAIN_MODEL` | Yozuvchi model nomi | `deepseek-v4-pro` |
| `LLM_MAIN_API_KEY` | 1-kalit | `sk-…` |
| `IMAGE_PROVIDER` | `openai` / `gemini` / `stability` / `replicate` / `fal` / `none` | `openai` |
| `IMAGE_MODEL` | Rasm modeli | `gpt-image-2` |
| `IMAGE_API_KEY` | 2-kalit | `sk-…` |
| `OPENAI_API_KEY` | 3-kalit (`gpt-6-sol` va `gpt-6-luna` uchun) | `sk-…` |
| `MONGODB_URI` | MongoDB ulanish manzili (Atlas: Connect → Drivers) | `mongodb+srv://user:parol@cluster…/` |
| `MONGODB_DB` | Bot bazasi nomi (boshqa bazalarga tegmaydi) | `it_dunyosi_bot` |
| `PEXELS_API_KEY` | Rasm qidirish uchun (bepul) | `…` |
| `DAILY_BUDGET_USD` | Kunlik AI budjeti | `3` |

Ixtiyoriy kalitlar: `NVD_API_KEY` (NVD limitini oshiradi), `GITHUB_TOKEN` (GitHub API limiti), `HASH_SALT` (boʻsh qolsa avtomatik yaratiladi), `MODEL_PRICES_JSON` (model narxlarini aniqlashtirish).

**DeepSeek haqida:** `deepseek-v4-pro` sifatliroq, `deepseek-flash` esa tezroq va arzonroq. Hisobingizdagi aniq model nomlarini `python scripts/check_ai.py` koʻrsatadi. DeepSeek modellari "oʻylovchi" (reasoning) modellar: javob byudjetga sigʻmasa, bot byudjetni avtomatik oshirib qayta soʻraydi.

---

## 4. Tekshirish skriptlari

| Buyruq | Nimani tekshiradi | Pul sarflaydimi |
|---|---|---|
| `python scripts/check_telegram.py` | Token, privacy rejimi, kanal va guruhlardagi admin huquqlari | Yoʻq (faqat oʻqiydi) |
| `python scripts/check_ai.py` | AI kalitlari, `gpt-6-sol`/`gpt-6-luna` va yozuvchi model mavjudligi | Yoʻq (modellar roʻyxati) |
| `python scripts/check_sources.py` | Har bir manbadan haqiqiy maʼlumot kelishi | Yoʻq |
| `python scripts/check_mongo.py` | MongoDB ulanishi, indekslar, vaqt zonasi, atomik yozuv (vaqtinchalik bazada, keyin oʻchiradi) | Yoʻq |
| `python scripts/golden_test.py 5` | "Oltin test": 5 ta haqiqiy maqola → post → fakt-tekshiruv. Telegram ga **hech narsa yubormaydi** | Ha, ~$0.1–0.3 |

`golden_test.py` natijalari `data/golden/results.json` ga yoziladi. Ularni oʻqib, post sifatini va tekshiruvchi qanday ishlayotganini koʻring.

---

## 5. Kompyuterda ishga tushirish

Python 3.12+ kerak.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      Linux/macOS:  source .venv/bin/activate
pip install -e ".[all,dev]"
python -m app
```

Ishga tushganda bot MongoDB dagi `MONGODB_DB` (standart `it_dunyosi_bot`) bazasiga ulanadi, indekslarni yaratadi, manbalar roʻyxatini qoʻshadi va sizga **"✅ Bot ishga tushdi"** xabarini yuboradi. Sozlamalarda muammo boʻlsa, ular shu xabarda koʻrsatiladi.

---

## 6. Serverga oʻrnatish (Docker)

1 vCPU va 1–2 GB RAM li VPS yetadi (Ubuntu 22.04/24.04).

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh

# 2. Loyiha
git clone <repo-manzili> it-dunyosi-bot && cd it-dunyosi-bot
cp .env.example .env && nano .env          # 3-boʻlimdagidek toʻldiring
mkdir -p data && sudo chown 1000:1000 data # konteyner 1000-foydalanuvchi bilan ishlaydi

# 3. Tekshirish va ishga tushirish
docker compose run --rm bot python scripts/check_telegram.py
docker compose run --rm bot python scripts/check_ai.py
docker compose up -d --build
docker compose logs -f --tail=100 bot
```

- **Faqat kerakli provayderlarni oʻrnatish:** `docker-compose.yml` dagi `EXTRAS` ni oʻzgartiring (`anthropic`, `gemini` yoki `all`). DeepSeek va OpenAI uchun qoʻshimcha paket kerak emas.
- **Oʻzini tiklash:** bot har daqiqada `data/heartbeat` faylini yangilaydi. 10 daqiqa yangilanmasa, healthcheck jarayonni toʻxtatadi va Docker uni qayta ishga tushiradi (`restart: unless-stopped`).
- **Backup:** har kuni 03:00 da barcha kolleksiyalar `data/backups/bot-…jsonl.gz` ga eksport qilinadi va 7 kun saqlanadi. Dushanba kunlari nusxa sizga Telegram orqali ham keladi. (Atlas bepul tarifida avtomatik backup yoʻq — shu eksport yordam beradi.)
- **Yangilash:** `make deploy` (yoki `git pull && docker compose up -d --build`). Baza migratsiyalari avtomatik bajariladi.

---

## 7. Kundalik ishlatish

### Tasdiqlash oynasi (`semi_auto`)

Har bir qoralama sizga quyidagi koʻrinishda keladi: rasm, post matni, muharrir bahosi (ball, xavf belgilari, tekshiruv natijasi) va manba havolalari. Ostida tugmalar bor:

| Tugma | Nima qiladi |
|---|---|
| ✅ Chiqarish | Darhol kanalga chiqaradi |
| 🕒 Vaqtga qoʻyish | Rejadagi vaqtga (yoki keyingi boʻsh slotga) qoʻyadi |
| ✏️ Tahrirlash | Tayyor matn yuborasiz **yoki** koʻrsatma berasiz ("qisqaroq qil", "rasmiyroq") |
| 🔄 Qayta yozish | Butunlay qaytadan yozadi |
| 🖼 Boshqa rasm | Qidiruvdagi keyingi bepul rasmni oladi (AI rejimida — yangisini chizadi) |
| ❌ Rad etish | Postni bekor qiladi |

**Bepul rasm topilmasa** post `auto` rejimda ham oʻzi chiqmaydi — sizga shu tugmalar bilan keladi:

| Tugma | Nima qiladi |
|---|---|
| 🎨 AI rasm (pullik) | 2-kalit bilan rasm chizadi (ikki marta bossangiz ham bir marta). `auto` da post rejaga qoʻyiladi, `semi_auto` da yangi rasm bilan sizga qayta keladi |
| 📝 Rasmsiz chiqarish | Post rasmsiz, oʻz vaqtida (yoki keyingi boʻsh slotda) chiqadi |
| ✏️ Tahrirlash, ❌ Rad etish | Odatdagidek |

Rasm faqat ruxsat etilgan litsenziyalardan olinadi: Pexels, Wikimedia da CC0, Public domain, CC BY va CC BY-SA (NC/ND yoʻq). Maqola va saytlardagi rasmlar olinmaydi. Muallif va litsenziya postning oxirida koʻrsatiladi. Rasm rejimini `/settings` dan oʻzgartirish mumkin: qidirish → topilmasa soʻrash (standart), doim AI, rasmsiz.

### Qoʻlda post (oʻzingizning postingiz)

1. Botga **rasm, video yoki GIF** yuboring (izohi bilan). Matnli post uchun avval `/new`, keyin matnni yuboring.
2. Bot "Qachon chiqarilsin?" deb soʻraydi: 🚀 Hozir · keyingi 3 ta boʻsh slot · ⏰ Boshqa vaqt (`HH:MM`, `DD.MM HH:MM`) · ❌ Bekor qilish.
3. Belgilangan vaqtda bot postni oʻzi chiqaradi. Navbatni `/queue` da koʻrasiz, `/show ID` post qanday chiqishini koʻrsatadi.

Izoh 1024 belgidan uzun boʻlsa, avval media, keyin matn alohida xabar boʻlib chiqadi. Slot tanlansa, AI shu slotga alohida post tayyorlamaydi. Albom (bir nechta fayl) hozircha qoʻllab-quvvatlanmaydi.

### Ulashish tugmasi

Har bir chiqqan post ostiga "📤 Ulashish" tugmasi qoʻshiladi: u Telegram'ning ulashish oynasini post havolasi bilan ochadi. `/settings` da oʻchirish mumkin (soʻrovnomalarga qoʻshilmaydi).

Yangiliklar 6 soat ichida tasdiqlanmasa eskiradi (`EXPIRED`). Ilova, sayt va maslahat postlari eskirmaydi. Javob bermasangiz, bot standart holatda **kutadi**. Buni `/set approval_timeout_action publish` bilan oʻzgartirish mumkin: shunda 30 daqiqadan keyin xavfsiz postlar oʻzi chiqadi.

### Admin buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/start` | Menyu |
| `/status` | Holat, navbat, bugungi xarajat |
| `/queue`, `/show ID`, `/time ID HH:MM` | Navbat, qoralamani koʻrish, vaqtni oʻzgartirish |
| `/post <mavzu yoki havola>` | Darhol post tayyorlash |
| `/new` yoki rasm/video/GIF yuborish | Oʻzingizning postingizni rejalashtirish |
| `/poll [mavzu]`, `/quiz [mavzu]` | Soʻrovnoma yoki test |
| `/digest` | Haftalik dayjest |
| `/sources`, `/source_add URL kategoriya` | Manbalar |
| `/mode auto\|semi_auto\|manual` | Nashr rejimi |
| `/pause`, `/resume` | Avtomatik nashrni toʻxtatish va davom ettirish |
| `/stats [7\|30]`, `/growth` | Statistika, oʻsish hisoboti va tavsiyalar |
| `/link <nom>` | Reklama yoki hamkorlik uchun nomli taklif havolasi |
| `/budget`, `/logs` | AI xarajati, oxirgi xatolar |
| `/settings` | Katakchali menyu: vaqtlar, turkumlar, soʻrovnoma/test soni, rasm rejimi, ulashish tugmasi |
| `/set kalit qiymat` | Boshqa sozlamalar: `/set slot_times 08:15,13:00`, `/set quiet.start 23:00` va h.k. |
| `/ask <savol>` yoki oddiy matn | AI maslahatchi |
| `/id` | Chat ID si |

### Bot oʻzi yuboradigan xabarlar

- **Har kuni 21:30**: kunlik hisobot (chiqqan postlar, reaksiyalar, obunachilar, xarajat, xatolar, moderatsiya).
- **Dushanba 09:00**: haftalik oʻsish hisoboti va 3–5 ta aniq tavsiya. 2 haftalik maʼlumot yigʻilgach, eng faol vaqtlar ham taklif qilinadi.
- **Darhol**: kritik xatolar, budjetning 80% sarflangani, ishlamay qolgan manbalar, shoshilinch kiber xabar qoralamasi. Bir xil xabar soatiga koʻpi bilan bir marta keladi.

### Obunachilar uchun

- Bot bilan shaxsiy chatda, izohlarda botni @mention qilib yoki unga reply qilib, kanal DM ida savol berish mumkin. Limit: daqiqasiga 3 ta, kuniga 20 ta savol.
- Izohlardagi spam, reklama, haqorat va firibgarlik oʻchiriladi. Takrorlansa foydalanuvchi ogohlantiriladi, keyin 24 soatga cheklanadi. Ban faqat sizning tugmangiz bilan.

---

## 8. Test rejimidan jonli rejimga oʻtish

1. `DRY_RUN=true` va `semi_auto` rejimida bot kamida 24–72 soat test kanalda ishlasin. Shu vaqt ichida postlar sifatini, rasmlarni va hisobotlarni koʻrib chiqing.
2. `python scripts/check_telegram.py` haqiqiy kanal uchun ham ✓ koʻrsatayotganini tekshiring.
3. `.env` da `DRY_RUN=false` qiling va qayta ishga tushiring: `docker compose up -d`.
4. Birinchi haftada `semi_auto` da qoling. `auto` ga keyinroq oʻting (`/mode auto`).

---

## 9. Xarajat va budjet

- `DAILY_BUDGET_USD` limitining 80% iga yetganda sizga ogohlantirish keladi. 100% ga yetganda faqat jadvaldagi postlar ishlashda davom etadi, savol-javob va maslahatchi esa ertangacha toʻxtaydi.
- `/budget` xarajatni rol, provayder va model boʻyicha koʻrsatadi.
- Taxminiy xarajat: bitta post (yozish, tekshirish va 1–2 tuzatish) ~$0.02–0.05, rasm ~$0.04–0.05. Kuniga 3 post bilan oyiga taxminan **$5–15**.
- Narxlar `app/ai/pricing.py` da. Aniq narxlarni `MODEL_PRICES_JSON` orqali kiritsa boʻladi, masalan: `{"deepseek-v4-pro": {"in": 0.5, "out": 2.0}}`.

---

## 10. Xavfsizlik

- Token va kalitlar faqat `.env` da saqlanadi. Ular logda maskalanadi va git ga tushmaydi.
- `DRY_RUN=true` boʻlsa, bot haqiqiy kanalga **hech qachon** yozmaydi.
- Botga "yangi admin qoʻshish" huquqini bermang. Kanal egasi doim inson boʻlib qoladi.
- Obunachilarning Telegram ID lari tuzli xesh koʻrinishida saqlanadi. Savol-javob va moderatsiya loglari 90 kundan keyin oʻchiriladi.
- AI oʻylab topgan havola boʻlsa, post rad etiladi. Postlarda faqat manbadagi va rasmiy domenlar ishlatiladi.
- Oʻzbekistondagi tashkilot "buzilgani" haqidagi xabar har doim sizning tasdigʻingizga keladi.

---

## 11. Muammolarni hal qilish

| Belgisi | Sabab va yechim |
|---|---|
| Bot ishga tushmaydi, ".env da notoʻgʻri qiymatlar" | Xabarda koʻrsatilgan kalitni tuzating (masalan, `CHANNEL_ID` raqam boʻlishi kerak) |
| "MongoDB ulanishini tekshiring" | `python scripts/check_mongo.py`; Atlas → Network Access da server IP manzili ruxsat etilganmi? |
| "chat not found" | Bot kanal yoki guruhga admin qilinmagan yoki ID notoʻgʻri. Guruh kanalga ulangach ID `-100…` ga oʻzgaradi |
| Izohlar moderatsiya qilinmayapti | BotFather → `/setprivacy` → Disable; `DISCUSSION_GROUP_ID` toʻgʻri superguruh ID simi? |
| Qoralamalar kelmayapti | `/status` (rejim `manual` emasmi, `/pause` holatida emasmi?), `/logs`, `/sources` |
| "OPENAI_API_KEY boʻsh" (kalit yozilgan boʻlsa ham) | `.env` da kalit ikki marta yozilgan, oxirgisi boʻsh. Takrorlangan qatorni oʻchiring |
| Yozuvchi ishlamaydi | `python scripts/check_ai.py` aniq model nomini koʻrsatadi |
| Hamma postlar tasdiqqa kelyapti (`auto` da ham) | Tekshiruvchi zaxira modelda ishlayapti (`OPENAI_API_KEY` ni tekshiring) yoki post xavfli deb belgilangan |

Loglar `data/logs/bot.log` va `data/logs/errors.log` da yoki `docker compose logs bot` orqali koʻriladi.

---

## 12. Dasturchilar uchun

```bash
make check     # ruff + mypy + pytest (390+ test)
make test
make sources   # manbalarni tekshirish
```

- Kod tuzilmasi va qoidalar `CLAUDE.md` da, amalga oshirish rejasi `docs/superpowers/plans/` da.
- Baza: MongoDB (`MONGODB_URI`, `MONGODB_DB`). Kolleksiyalar va indekslar ishga tushganda avtomatik yaratiladi; migratsiya kerak emas. Testlar mongomock asosidagi soxta bazada ishlaydi.
- Shriftlar: Inter (SIL Open Font License, `assets/fonts/OFL.txt`).
- Kiritilmagan imkoniyatlar (SPEC 7-bosqich): Telethon orqali koʻrishlar statistikasi va webhook. Hozircha long polling ishlatiladi.
