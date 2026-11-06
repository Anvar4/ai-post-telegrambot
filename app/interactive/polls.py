"""So'rovnomalar: yaratish, natijalarni yig'ish, yopish, auditoriya konteksti."""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import select

from app.ai.prompts import load_prompt
from app.ai.schemas import PollDraft
from app.ai.types import Message
from app.content.formatting import escape, normalize_uz
from app.content.limits import validate_poll
from app.db.models import Poll, Post
from app.pipeline.state import PostKind, PostStatus, transition
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext

S = PostStatus
POLL_MAX_OPTIONS_UI = 6
FUN_TOPICS = [
    "qaysi brauzerdan foydalanasiz",
    "qaysi messenjer eng qulay",
    "smartfon operatsion tizimi",
    "eng foydali AI vositasi",
    "birinchi oʻrganilgan dasturlash tili",
    "parollarni qanday saqlaysiz",
    "kuniga ekran oldida necha soat",
    "eng koʻp ishlatiladigan ilova turi",
    "ish stoli: Windows, macOS yoki Linux",
]
RESEARCH_TOPICS = [
    "auditoriyaning asosiy qurilmasi (telefon yoki kompyuter)",
    "kanalda qaysi mavzular koʻproq qiziq",
    "IT boʻyicha bilim darajasi",
    "IT bilan bogʻliqlik (oʻquvchi, talaba, dasturchi, foydalanuvchi)",
    "qaysi formatdagi postlar foydali (yangilik, maslahat, test)",
    "kiberxavfsizlik boʻyicha xabardorlik darajasi",
]


async def create_poll_post(
    ctx: AppContext,
    *,
    kind: PostKind,
    question: str,
    options: list[str],
    purpose: str,
    topic: str | None,
    scheduled_at: datetime | None,
    slot: str | None,
    created_by: str,
    correct_option_id: int | None = None,
    explanation: str | None = None,
    needs_approval: bool = False,
    approval_reason: str | None = None,
) -> int:
    """So'rovnoma/test postini yaratadi (CHECKED) va nashr rejimiga ko'ra navbatga yoki tasdiqqa yuboradi."""
    quiz = kind == PostKind.QUIZ
    poll_data: dict[str, Any] = {"question": question, "options": options, "quiz": quiz}
    if quiz:
        poll_data["correct_option_id"] = correct_option_id
        poll_data["explanation"] = explanation or ""
    async with ctx.repo.session() as s:
        post = Post(
            kind=kind,
            status=S.NEW,
            text_html=escape(question),
            title_short=question[:60],
            slot=slot,
            scheduled_at=scheduled_at,
            publish_key=uuid.uuid4().hex,
            created_by=created_by,
            needs_approval=needs_approval or created_by == "admin",
            approval_reason=approval_reason,
            extra={"poll": poll_data, "category": "test" if quiz else "sorovnoma", "purpose": purpose},
            check_report={
                "verdict": "pass" if not needs_approval else "fix",
                "issues": [],
                "code_issues": [],
            },
        )
        s.add(post)
        await s.flush()
        for status in (S.SELECTED, S.DRAFTED, S.CHECKED):
            await transition(s, post, status, created_by)
        s.add(
            Poll(
                post_id=post.id,
                question=question,
                options=options,
                purpose=purpose,
                topic=topic,
                correct_option_ids=[correct_option_id] if quiz and correct_option_id is not None else [],
                explanation=explanation,
            )
        )
        await s.commit()
        pid = post.id
    await ctx.service("pipeline").after_check(pid)
    return pid


class PollService:
    def __init__(
        self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow, rng: random.Random | None = None
    ) -> None:
        self.ctx = ctx
        self.clock = clock
        self.rng = rng or random.Random()

    async def _recent_topics(self, days: int = 30) -> set[str]:
        async with self.ctx.repo.session() as s:
            rows = await s.execute(
                select(Poll.topic).where(Poll.created_at >= self.clock() - timedelta(days=days))
            )
            return {t for t in rows.scalars() if t}

    async def _next_purpose(self) -> str:
        async with self.ctx.repo.session() as s:
            last = await s.scalar(
                select(Poll.purpose)
                .where(Poll.purpose.in_(("fun", "research")))
                .order_by(Poll.id.desc())
                .limit(1)
            )
        return "research" if last == "fun" else "fun"

    async def create(
        self,
        topic: str | None,
        *,
        scheduled_at: datetime | None = None,
        slot: str | None = None,
        purpose: str | None = None,
        created_by: str = "ai",
    ) -> int | None:
        purpose = purpose or await self._next_purpose()
        if topic is None:
            pool = RESEARCH_TOPICS if purpose == "research" else FUN_TOPICS
            recent = await self._recent_topics()
            topic = self.rng.choice([t for t in pool if t not in recent] or pool)
        messages = [
            Message("system", load_prompt("poll"), cache=True),
            Message("user", f"Mavzu: {topic}\nMaqsad: {purpose}"),
        ]
        for attempt in range(2):
            res = await self.ctx.router.complete(
                "writer", messages, schema=PollDraft, temperature=0.7, max_tokens=600
            )
            draft: PollDraft = res.parsed
            question = normalize_uz(draft.question.strip())
            options = [normalize_uz(o.strip()) for o in draft.options if o.strip()]
            errors = validate_poll(question, options)
            if len(options) > POLL_MAX_OPTIONS_UI:
                errors.append(f"soʻrovnomada 2–{POLL_MAX_OPTIONS_UI} variant boʻlsin")
            if not errors:
                return await create_poll_post(
                    self.ctx,
                    kind=PostKind.POLL,
                    question=question,
                    options=options,
                    purpose=purpose,
                    topic=topic,
                    scheduled_at=scheduled_at,
                    slot=slot,
                    created_by=created_by,
                    needs_approval=res.fallback_used,
                )
            logger.info("So'rovnoma qoralamasi limitlardan o'tmadi ({}): {}", attempt + 1, errors)
            messages = [
                *messages,
                Message("assistant", res.text),
                Message(
                    "user",
                    "Xatolar: " + "; ".join(errors) + ". Tuzatib, qaytadan JSON ber "
                    f"(2–{POLL_MAX_OPTIONS_UI} variant, har biri ≤100 belgi).",
                ),
            ]
        await self.ctx.notifier.notify(
            "ℹ️ Soʻrovnoma tayyorlanmadi (limitlarga mos kelmadi).", key="poll-failed"
        )
        return None

    async def on_poll_update(
        self, poll_id: str, options: Sequence[tuple[str, int]], total: int, is_closed: bool
    ) -> None:
        async with self.ctx.repo.session() as s:
            poll = (
                await s.execute(select(Poll).where(Poll.telegram_poll_id == poll_id))
            ).scalar_one_or_none()
            if poll is None:
                return
            poll.results = {text: int(count) for text, count in options}
            poll.total_voters = int(total)
            if is_closed:
                poll.closed = True
            await s.commit()

    async def close_due(self, now: datetime | None = None) -> int:
        now = now or self.clock()
        async with self.ctx.repo.session() as s:
            rows = (
                await s.execute(
                    select(Poll, Post)
                    .join(Post, Post.id == Poll.post_id)
                    .where(
                        Poll.closed.is_(False),
                        Poll.closes_at <= now,
                        Post.message_id.is_not(None),
                        Post.chat_id.is_not(None),
                    )
                )
            ).all()
        closed = 0
        for poll, post in rows:
            result: dict[str, Any] = {}
            try:
                result = await self.ctx.sender.stop_poll(int(post.chat_id or 0), int(post.message_id or 0))
            except Exception as exc:
                logger.warning("So'rovnoma #{} yopilmadi: {}", poll.id, exc)
            async with self.ctx.repo.session() as s:
                row = await s.get(Poll, poll.id)
                if row is None:
                    continue
                row.closed = True
                if result.get("options"):
                    row.results = {o["text"]: int(o["voter_count"]) for o in result["options"]}
                    row.total_voters = int(result.get("total_voter_count", 0))
                await s.commit()
                closed += 1
                if row.purpose == "research" and row.total_voters:
                    await self.ctx.notifier.notify(f"📊 Tadqiqot soʻrovnomasi yakunlandi:\n{_summary(row)}")
        return closed

    async def research_context(self, days: int = 90) -> str:
        async with self.ctx.repo.session() as s:
            rows = (
                (
                    await s.execute(
                        select(Poll)
                        .where(
                            Poll.purpose == "research",
                            Poll.total_voters > 0,
                            Poll.created_at >= self.clock() - timedelta(days=days),
                        )
                        .order_by(Poll.id.desc())
                        .limit(10)
                    )
                )
                .scalars()
                .all()
            )
        return "\n".join(_summary(p) for p in rows)


def _summary(poll: Poll) -> str:
    total = poll.total_voters or sum(poll.results.values()) or 1
    parts = ", ".join(f"{k} {round(v * 100 / total)}%" for k, v in poll.results.items())
    return f"{poll.question}: {parts} ({poll.total_voters} ovoz)"


def poll_json(poll: Poll) -> str:
    return json.dumps({"question": poll.question, "results": poll.results}, ensure_ascii=False)
