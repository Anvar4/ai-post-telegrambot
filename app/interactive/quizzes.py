"""Testlar (quiz): yozuvchi tuzadi, gpt-6-sol javobsiz holda mustaqil yechib tekshiradi."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select

from app.ai.prompts import load_prompt
from app.ai.schemas import QuizDraft, QuizVerify
from app.ai.types import Message
from app.content.formatting import normalize_uz
from app.content.limits import validate_quiz
from app.db.models import Poll
from app.interactive.polls import create_poll_post
from app.pipeline.state import PostKind
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext

QUIZ_TOPICS = [
    "kiberxavfsizlik gigienasi",
    "IT terminlari",
    "IT tarixi",
    "klaviatura yorliqlari",
    "AI asoslari",
    "dasturlash asoslari",
]
LEVELS = ["oson", "oʻrta", "qiyin"]
MIN_CONFIDENCE = 0.7
ATTEMPTS = 2


class QuizService:
    def __init__(
        self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow, rng: random.Random | None = None
    ) -> None:
        self.ctx = ctx
        self.clock = clock
        self.rng = rng or random.Random()

    async def _pick_topic(self) -> str:
        async with self.ctx.repo.session() as s:
            recent = {
                t
                for t in (
                    await s.execute(
                        select(Poll.topic).where(
                            Poll.purpose == "quiz", Poll.created_at >= self.clock() - timedelta(days=10)
                        )
                    )
                ).scalars()
                if t
            }
        return self.rng.choice([t for t in QUIZ_TOPICS if t not in recent] or QUIZ_TOPICS)

    async def create(
        self,
        topic: str | None,
        *,
        scheduled_at: datetime | None = None,
        slot: str | None = None,
        level: str | None = None,
        created_by: str = "ai",
    ) -> int | None:
        for attempt in range(ATTEMPTS):
            t = topic or await self._pick_topic()
            lvl = level or self.rng.choice(LEVELS)
            res = await self.ctx.router.complete(
                "writer",
                [
                    Message("system", load_prompt("quiz"), cache=True),
                    Message("user", f"Mavzu: {t}\nQiyinlik: {lvl}"),
                ],
                schema=QuizDraft,
                temperature=0.7,
                max_tokens=700,
            )
            draft: QuizDraft = res.parsed
            question = normalize_uz(draft.question.strip())
            options = [normalize_uz(o.strip()) for o in draft.options]
            explanation = normalize_uz(draft.explanation.strip())
            errors = validate_quiz(question, options, draft.correct_index, explanation)
            if errors:
                logger.info("Test limitlardan o'tmadi ({}): {}", attempt + 1, errors)
                continue
            verified, degraded = await self._verify(question, options, draft.correct_index)
            if not verified:
                logger.info("Test mustaqil tekshiruvdan o'tmadi ({})", attempt + 1)
                continue
            return await create_poll_post(
                self.ctx,
                kind=PostKind.QUIZ,
                question=question,
                options=options,
                purpose="quiz",
                topic=t,
                scheduled_at=scheduled_at,
                slot=slot,
                created_by=created_by,
                correct_option_id=draft.correct_index,
                explanation=explanation,
                needs_approval=degraded,
                approval_reason="Javobni zaxira model tekshirdi" if degraded else None,
            )
        await self.ctx.notifier.notify(
            "ℹ️ Test tayyorlanmadi: javob mustaqil tekshiruvdan oʻtmadi.", key="quiz-failed"
        )
        return None

    async def _verify(self, question: str, options: list[str], correct: int) -> tuple[bool, bool]:
        """Variantlarni aralashtirib, javobsiz yechtiradi. (to'g'rimi, zaxira model ishladimi)."""
        order = self.rng.sample(range(len(options)), len(options))
        shown = "\n".join(f"{i}) {options[j]}" for i, j in enumerate(order))
        res = await self.ctx.router.complete(
            "editor",
            [
                Message("system", load_prompt("quiz_verify"), cache=True),
                Message("user", f"Savol: {question}\nVariantlar:\n{shown}"),
            ],
            schema=QuizVerify,
            temperature=0.0,
            max_tokens=400,
        )
        v: QuizVerify = res.parsed
        if not 0 <= v.answer_index < len(order):
            return False, res.fallback_used
        ok = order[v.answer_index] == correct and not v.ambiguous and v.confidence >= MIN_CONFIDENCE
        return ok, res.fallback_used
