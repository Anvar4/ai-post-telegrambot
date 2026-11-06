"""Izohlar moderatsiyasi: gpt-6-luna tasnifi; o'chirish → ogohlantirish → 24 soat mute; ban faqat admin."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from loguru import logger

from app.ai.prompts import load_prompt
from app.ai.schemas import ModerationOutput
from app.ai.types import Message
from app.bot.keyboards import ban_keyboard
from app.content.formatting import escape, wrap_external
from app.db.models import ModerationEvent
from app.utils.security import hash_user_id
from app.utils.timeutil import day_bounds, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

Action = Literal["none", "delete", "warn", "mute", "ban"]
LINK_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|@[A-Za-z0-9_]{5,})", re.I)
MIN_CONFIDENCE = 0.6
ALLOWED_LABELS = frozenset({"ok", "offtopic"})
NEW_MEMBER_WINDOW = timedelta(hours=24)


@dataclass
class ModerationAction:
    label: str
    action: Action


class ModerationService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock
        self._new_members: dict[tuple[int, int], datetime] = {}

    def mark_new_member(self, chat_id: int, user_id: int) -> None:
        self._new_members[(chat_id, user_id)] = self.clock()

    def pop_first_message(self, chat_id: int, user_id: int) -> bool:
        joined = self._new_members.pop((chat_id, user_id), None)
        return joined is not None and self.clock() - joined <= NEW_MEMBER_WINDOW

    async def handle(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        text: str,
        *,
        is_new_member_first_msg: bool,
        has_link: bool = False,
        user_name: str | None = None,
    ) -> ModerationAction:
        if self.ctx.settings.is_admin(user_id):
            return ModerationAction("ok", "none")
        user_hash = hash_user_id(user_id, self.ctx.salt)
        if is_new_member_first_msg and (has_link or LINK_RE.search(text)):
            await self._delete(chat_id, message_id)
            await self._record(chat_id, user_hash, text, "ad_link", "delete")
            return ModerationAction("ad_link", "delete")
        if not text.strip():
            return ModerationAction("ok", "none")
        try:
            res = await self.ctx.router.complete(
                "fast",
                [
                    Message("system", load_prompt("moderation"), cache=True),
                    Message("user", wrap_external("user", text[:1500])),
                ],
                schema=ModerationOutput,
                temperature=0.0,
                max_tokens=100,
            )
        except Exception as exc:  # shubha bo'lsa o'tkazib yuboramiz
            logger.warning("Moderatsiya tasnifi ishlamadi: {}", exc)
            return ModerationAction("ok", "none")
        out: ModerationOutput = res.parsed
        if out.label in ALLOWED_LABELS or out.confidence < MIN_CONFIDENCE:
            return ModerationAction(out.label, "none")
        prior = await self._prior_violations(chat_id, user_hash)
        action: Action = "delete" if prior == 0 else "warn" if prior == 1 else "mute"
        await self._delete(chat_id, message_id)
        if action == "warn":
            who = escape(user_name) if user_name else "Hurmatli foydalanuvchi"
            await self._safe_send(
                chat_id,
                f"⚠️ {who}, iltimos, guruh qoidalariga rioya qiling: spam, reklama, "
                "haqorat va firibgarlik oʻchiriladi. Takrorlansa — 24 soatga cheklov.",
            )
        elif action == "mute":
            try:
                await self.ctx.sender.restrict(chat_id, user_id, self.clock() + timedelta(hours=24))
            except Exception as exc:
                logger.warning("Mute qilib bo'lmadi: {}", exc)
            for admin_id in self.ctx.settings.admin_ids:
                await self._safe_send(
                    admin_id,
                    f"🛡 Foydalanuvchi 3-marta qoidani buzdi ({out.label}) va 24 soatga cheklandi.\n"
                    f"Xabar: «{escape(text[:200])}»\nBan qilinsinmi?",
                    reply_markup=ban_keyboard(chat_id, user_id),
                )
        await self._record(chat_id, user_hash, text, out.label, action)
        return ModerationAction(out.label, action)

    async def ban(self, chat_id: int, user_id: int) -> None:
        await self.ctx.sender.ban(chat_id, user_id)
        await self._record(chat_id, hash_user_id(user_id, self.ctx.salt), "", "ban", "ban")

    async def _prior_violations(self, chat_id: int, user_hash: str) -> int:
        return await self.ctx.repo.moderation_events.count(
            {
                "user_hash": user_hash,
                "chat_id": chat_id,
                "action": {"$ne": "none"},
                "ts": {"$gte": self.clock() - timedelta(days=7)},
            }
        )

    async def _delete(self, chat_id: int, message_id: int) -> None:
        try:
            await self.ctx.sender.delete_message(chat_id, message_id)
        except Exception as exc:
            logger.warning("Xabar o'chirilmadi: {}", exc)

    async def _safe_send(self, chat_id: int, text: str, reply_markup: object = None) -> None:
        try:
            await self.ctx.sender.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as exc:
            logger.warning("Xabar yuborilmadi: {}", exc)

    async def _record(self, chat_id: int, user_hash: str, text: str, label: str, action: str) -> None:
        await self.ctx.repo.moderation_events.insert(
            ModerationEvent(
                ts=self.clock(),
                chat_id=chat_id,
                user_hash=user_hash,
                excerpt=text[:200],
                label=label,
                action=action,
            )
        )

    async def daily_summary(self, now: datetime | None = None) -> str:
        start, end = day_bounds(now or self.clock(), self.ctx.settings.tz)
        events = await self.ctx.repo.moderation_events.find({"ts": {"$gte": start, "$lt": end}})
        rows = [(e.label, e.action) for e in events]
        if not rows:
            return "🛡 Moderatsiya: bugun qoidabuzarlik yoʻq."
        labels = Counter(r[0] for r in rows)
        actions = Counter(r[1] for r in rows)
        return (
            f"🛡 Moderatsiya (bugun): {len(rows)} ta hodisa — "
            + ", ".join(f"{k} {v}" for k, v in labels.most_common())
            + f"\noʻchirildi {actions['delete'] + actions['warn'] + actions['mute']}, "
            f"ogohlantirildi {actions['warn']}, cheklandi {actions['mute']}, ban {actions['ban']}"
        )
