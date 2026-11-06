"""Savol-javob: shaxsiy chat, izohlar guruhi va kanal DM (1-model, ≤700 belgi)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from loguru import logger

from app.ai.prompts import load_prompt
from app.ai.types import BudgetExceededError, Message
from app.collectors.dedupe import title_similarity
from app.content.formatting import normalize_uz, sanitize_html, truncate_visible, wrap_external
from app.content.limits import QA_ANSWER_LIMIT
from app.db.models import QALog
from app.interactive.ratelimit import RateLimiter
from app.pipeline.state import PostKind
from app.utils.security import hash_user_id
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.context import AppContext

Channel = Literal["dm", "comments", "channel_dm"]

_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)")
_CODE_RE = re.compile(r"(?i)\b(kod|code|sms)\b\s*[:=\-]?\s*\d{4,8}\b")
_SECRET_RE = re.compile(r"(?i)\b(parol|password|pin|cvv|cvc)\s*[:=]\s*\S{3,}")
_UZ_CARD_PREFIXES = ("8600", "9860", "5614", "6262", "4278")

SENSITIVE_WARNING = (
    "⚠️ Xabaringizda maxfiy maʼlumot (karta raqami, SMS kod yoki parol) bor koʻrinadi. "
    "Iltimos, uni oʻchiring va hech kimga — hatto botga ham — bermang. "
    "Hech bir rasmiy xizmat bunday maʼlumotni soʻramaydi."
)
MINUTE_LIMIT = "⏳ Juda tez yozyapsiz — bir daqiqada 3 tagacha savol. Birozdan keyin qayta urinib koʻring."
DAY_LIMIT = "Bugungi savollar limiti (20 ta) tugadi. Ertaga yana yozing 🙂"
PAUSED = "Savol-javob xizmati bugun vaqtincha toʻxtatildi. Ertaga qayta yozing."
FAILED = "Hozir javob bera olmayman. Birozdan keyin qayta urinib koʻring."


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def contains_sensitive(text: str) -> bool:
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) == 16 and (digits.startswith(_UZ_CARD_PREFIXES) or _luhn(digits)):
            return True
    return bool(_CODE_RE.search(text) or _SECRET_RE.search(text))


def mask_digits(text: str) -> str:
    return re.sub(r"\d", "•", text)


class QAService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock
        self.limiter = RateLimiter(per_minute=3, per_day=20, tz=ctx.settings.tz)

    async def answer(self, user_id: int, text: str, channel: Channel) -> str:
        user_hash = hash_user_id(user_id, self.ctx.salt)
        is_admin = self.ctx.settings.is_admin(user_id)
        if not is_admin:
            status = self.limiter.check(user_hash, self.clock())
            if status == "minute":
                return MINUTE_LIMIT
            if status == "day":
                return DAY_LIMIT
        question = text.strip()[:2000]
        if contains_sensitive(question):
            await self._log(user_hash, channel, mask_digits(question), SENSITIVE_WARNING, flagged=True)
            return SENSITIVE_WARNING
        try:
            res = await self.ctx.router.complete(
                "writer",
                [
                    Message("system", load_prompt("qa"), cache=True),
                    Message("user", wrap_external("user", question)),
                ],
                temperature=0.3,
                max_tokens=700,
                essential=False,
            )
        except BudgetExceededError:
            return PAUSED
        except Exception as exc:
            logger.warning("Savol-javob xatosi: {}", exc)
            return FAILED
        answer = truncate_visible(sanitize_html(normalize_uz(res.text.strip())), QA_ANSWER_LIMIT)
        await self._log(user_hash, channel, question, answer, flagged=False)
        return answer or FAILED

    async def _log(self, user_hash: str, channel: str, question: str, answer: str, *, flagged: bool) -> None:
        await self.ctx.repo.qa_logs.insert(
            QALog(
                user_hash=user_hash,
                channel=channel,
                question=question,
                answer=answer,
                flagged=flagged,
                ts=self.clock(),
            )
        )

    async def frequent_questions(self, days: int = 7, min_count: int = 2) -> list[tuple[str, int]]:
        logs = await self.ctx.repo.qa_logs.find(
            {"ts": {"$gte": self.clock() - timedelta(days=days)}, "flagged": False}
        )
        rows = [q.question for q in logs]
        groups: list[tuple[str, int]] = []
        for q in rows:
            for i, (rep, count) in enumerate(groups):
                if title_similarity(q, rep) >= 70:
                    groups[i] = (rep, count + 1)
                    break
            else:
                groups.append((q, 1))
        return sorted([g for g in groups if g[1] >= min_count], key=lambda g: -g[1])[:6]

    async def weekly_faq(self) -> int | None:
        """Ko'p takrorlangan savollardan 'Savol-javob' posti (faqat admin tasdig'i bilan)."""
        frequent = await self.frequent_questions()
        if len(frequent) < 3:
            return None
        pipeline = self.ctx.service("pipeline")
        source = json.dumps([{"savol": q, "necha_marta": n} for q, n in frequent], ensure_ascii=False)
        pid: int | None = await pipeline.prepare_custom(
            PostKind.QA,
            source_text=source,
            story_title="Haftaning koʻp soʻralgan savollari",
            category="savoljavob",
            force_approval=True,
        )
        return pid
