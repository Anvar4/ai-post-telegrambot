"""Post shablonlari (SPEC 5-bo'lim). `{KANAL}` — kanal username."""

from __future__ import annotations

from app.pipeline.state import PostKind

ALERT = """🔴 <b>OGOHLANTIRISH: {qisqa sarlavha}</b>

{1–2 jumla: nima bo'ldi}

<b>Kimga ta'sir qiladi:</b> {mahsulot, versiyalar}
<b>Xavf darajasi:</b> {manbadagi daraja: Kritik / Yuqori / O'rta — manbada boʻlmasa qatorni tushir}
<b>CVE:</b> {CVE raqami, boʻlsa}
<b>Nima qilish kerak:</b>
• {amaliy qadam 1}
• {amaliy qadam 2}

🔗 <a href="{url}">Manba: {manba nomi}</a>

#kiberxavfsizlik #ogohlantirish
👉 {KANAL}"""

NEWS = """📰 <b>{sarlavha}</b>

{2–4 jumla: asosiy fakt va raqamlar}

💡 <b>Bu nima uchun muhim:</b> {1–2 jumla, o'zbek foydalanuvchisi uchun}

🔗 <a href="{url}">Batafsil: {manba}</a>
#yangilik #{teg}
👉 {KANAL}"""

TOOL = """🛠 <b>{nomi}</b> — {bir qatorda nima qiladi}

✅ {afzallik 1}
✅ {afzallik 2}
✅ {afzallik 3}

💰 Narxi: {Bepul / Freemium / Pullik}
📱 Platforma: {Web / Android / iOS / Windows / macOS}

🔗 <a href="{rasmiy_url}">{domen}</a>
#ilova
👉 {KANAL}"""

SITE = """🌐 <b>{nomi}</b> — {bir qatorda nima qiladi}

✅ {foyda 1}
✅ {foyda 2}
✅ {foyda 3}

💰 Narxi: {Bepul / Freemium / Pullik}

🔗 <a href="{rasmiy_url}">{domen}</a>
#sayt
👉 {KANAL}"""

TIP = """💡 <b>{sarlavha}</b>

{1–2 jumla: vaziyat yoki muammo}

<b>Nima qilish kerak:</b>
• {qadam 1}
• {qadam 2}
• {qadam 3}

{1 jumla: natija yoki foyda}
#maslahat
👉 {KANAL}"""

DIGEST = """🗓 <b>Hafta dayjesti</b>

{1 jumla: hafta haqida}

1. {emoji} <a href="{post havolasi}">{qisqa sarlavha}</a>
2. ...
(5–7 ta)

{1 jumla: ulashishga chaqiriq}
#dayjest
👉 {KANAL}"""

QA = """❓ <b>Savol-javob: {mavzu}</b>

<b>S:</b> {savol 1}
<b>J:</b> {javob 1}

<b>S:</b> {savol 2}
<b>J:</b> {javob 2}

#savoljavob
👉 {KANAL}"""

TEMPLATES: dict[PostKind, str] = {
    PostKind.ALERT: ALERT,
    PostKind.NEWS: NEWS,
    PostKind.TOOL: TOOL,
    PostKind.SITE: SITE,
    PostKind.TIP: TIP,
    PostKind.DIGEST: DIGEST,
    PostKind.QA: QA,
}

KIND_EMOJI: dict[PostKind, str] = {
    PostKind.ALERT: "🔴",
    PostKind.NEWS: "📰",
    PostKind.TOOL: "🛠",
    PostKind.SITE: "🌐",
    PostKind.TIP: "💡",
    PostKind.POLL: "📊",
    PostKind.QUIZ: "🧠",
    PostKind.DIGEST: "🗓",
    PostKind.QA: "❓",
}

KIND_LABEL: dict[PostKind, str] = {
    PostKind.ALERT: "KIBERXAVFSIZLIK",
    PostKind.NEWS: "YANGILIK",
    PostKind.TOOL: "ILOVA",
    PostKind.SITE: "SAYT",
    PostKind.TIP: "MASLAHAT",
    PostKind.POLL: "SOʻROVNOMA",
    PostKind.QUIZ: "TEST",
    PostKind.DIGEST: "DAYJEST",
    PostKind.QA: "SAVOL-JAVOB",
}

SHARE_CTA = "📢 Foydali boʻlsa, doʻstlaringizga ulashing!"


def render_footer(username: str) -> str:
    return f"👉 {username}" if username else ""


def template_for(kind: PostKind | str, username: str) -> str:
    tpl = TEMPLATES.get(PostKind(kind), NEWS)
    return tpl.replace("{KANAL}", username or "@kanal")
