"""Orkestrator testlari uchun soxta AI javoblari va ma'lumotlar."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.ai.types import Message
from app.db.models import Article, Source, Story
from tests.conftest import use_llm
from tests.fakes import RoutedLLM

SRC_URL = "https://www.bleepingcomputer.com/news/security/chrome-zero-day/"
BODY = "Google Chrome brauzerida faol foydalanilayotgan zaiflik topildi va yangilanish chiqdi. " * 6


def ids_from(messages: list[Message]) -> list[int]:
    text = messages[-1].content
    return [int(x) for x in re.findall(r'"id":\s*(\d+)', text)]


def post_html(title: str = "Chrome zaifligi", link: str = SRC_URL) -> str:
    return (
        f"🔴 <b>OGOHLANTIRISH: {title}</b>\n\n{BODY}\n\n"
        f'🔗 <a href="{link}">Manba: BleepingComputer</a>\n#kiberxavfsizlik #ogohlantirish'
    )


def writer_answer(title: str = "Chrome zaifligi", link: str = SRC_URL) -> str:
    return json.dumps(
        {
            "title_short": title,
            "text_html": post_html(title, link),
            "hashtags": ["#kiberxavfsizlik"],
            "image_prompt_en": "browser shield",
        }
    )


def make_llms(
    ctx: Any,
    *,
    verdict: str = "pass",
    score: int = 80,
    breaking: bool = False,
    category: str = "kiber",
    writer_link: str = SRC_URL,
) -> dict[str, RoutedLLM]:
    def scores(msgs: list[Message]) -> str:
        return json.dumps(
            {
                "items": [
                    {
                        "id": i,
                        "score": score,
                        "category": category,
                        "is_breaking": breaking,
                        "why_uz": "muhim",
                        "risk_flags": [],
                    }
                    for i in ids_from(msgs)
                ]
            }
        )

    def relevant(msgs: list[Message]) -> str:
        return json.dumps(
            {"items": [{"id": i, "relevant": True, "category": category} for i in ids_from(msgs)]}
        )

    tip_html = (
        "💡 <b>Ikki bosqichli himoya</b>\n\n"
        + BODY
        + "\n\n<b>Nima qilish kerak:</b>\n• Sozlamalarni oching\n• 2FA ni yoqing\n#maslahat"
    )
    writer = RoutedLLM(
        "anthropic",
        "claude-x",
        [
            (
                "maslahat mavzusini tanla",
                json.dumps(
                    {"topic": "Ikki bosqichli autentifikatsiya", "angle": "Telegram va Gmail uchun yoqish"}
                ),
            ),
            (
                '"tip" turidagi',
                json.dumps(
                    {
                        "title_short": "Ikki bosqichli himoya",
                        "text_html": tip_html,
                        "hashtags": ["#maslahat"],
                        "image_prompt_en": "lock",
                    }
                ),
            ),
            ("bosh muallifisan", writer_answer(link=writer_link)),
            (
                "Haftalik dayjest",
                json.dumps(
                    {
                        "title_short": "Hafta dayjesti",
                        "text_html": "🗓 <b>Hafta dayjesti</b>\n\n" + BODY,
                        "hashtags": ["#dayjest"],
                        "image_prompt_en": "calendar",
                    }
                ),
            ),
        ],
    )
    editor = RoutedLLM(
        "openai",
        "gpt-6-sol",
        [
            ("fakt-tekshiruvchisan", json.dumps({"verdict": verdict, "issues": []})),
            ("bosh muharririsan", scores),
        ],
    )
    fast = RoutedLLM("openai", "gpt-6-luna", [("tez filtrsan", relevant)])
    use_llm(ctx, writer=writer, editor=editor, fast=fast)
    return {"writer": writer, "editor": editor, "fast": fast}


async def seed_story(
    ctx: Any,
    *,
    title: str = "Chrome zero-day exploited in attacks",
    now: datetime,
    summary: str = "Google patched CVE-2026-1234 exploited in the wild.",
    source_category: str = "kiber",
) -> int:
    async with ctx.repo.session() as s:
        src = Source(
            name="BleepingComputer",
            type="rss",
            url=f"https://bc.example/feed/{title[:10]}",
            category=source_category,
            trust=4,
        )
        s.add(src)
        await s.flush()
        st = Story(title=title, status="new", source_category=source_category, first_seen=now, last_seen=now)
        s.add(st)
        await s.flush()
        s.add(
            Article(
                source_id=src.id,
                url=SRC_URL,
                url_hash=f"h-{st.id}",
                title=title,
                summary=summary,
                story_id=st.id,
                fetched_at=now,
            )
        )
        await s.commit()
        return st.id
