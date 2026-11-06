"""Nashr qiluvchi: idempotent, DRY_RUN himoyasi, 3 urinish, qayta ishga tushganda tiklash."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select

from app.content.formatting import visible_length
from app.content.limits import CAPTION_LIMIT
from app.content.templates import SHARE_CTA
from app.db.models import Poll, Post
from app.pipeline.compose import compose
from app.pipeline.state import PostKind, PostStatus, transition
from app.utils.security import mask_secrets
from app.utils.timeutil import utcnow

if TYPE_CHECKING:
    from app.bot.notify import AdminNotifier
    from app.bot.sender import TelegramSender
    from app.config import Settings
    from app.db.repo import Repo
    from app.utils.runtime import Runtime

MAX_ATTEMPTS = 3
CTA_KINDS = frozenset({PostKind.NEWS, PostKind.TOOL, PostKind.SITE, PostKind.TIP})
EXPIRING_KINDS = frozenset({PostKind.NEWS, PostKind.ALERT, PostKind.DIGEST})
POLL_HOURS = {"fun": 24, "quiz": 24, "research": 48}


class Publisher:
    def __init__(
        self,
        repo: Repo,
        sender: TelegramSender,
        settings: Settings,
        notifier: AdminNotifier,
        *,
        runtime: Runtime | None = None,
        on_published: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self.repo = repo
        self.sender = sender
        self.settings = settings
        self.notifier = notifier
        self.runtime = runtime
        self.on_published = on_published

    async def publish(self, post_id: int) -> bool:
        chat_id = self.settings.target_chat_id
        if chat_id is None:
            await self.notifier.notify(
                "⚠️ Post chiqadigan chat sozlanmagan (DRY_RUN=true bo'lsa TEST_CHANNEL_ID kerak).",
                key="no-target-chat",
            )
            return False
        async with self.repo.session() as s:
            post = await s.get(Post, post_id)
            if post is None:
                return False
            if post.status == PostStatus.PUBLISHED:
                return True
            if post.status != PostStatus.SCHEDULED:
                return False
            await self._maybe_add_cta(post)
            await transition(s, post, PostStatus.PUBLISHING, "publisher", chat_id=chat_id)
            post.chat_id = chat_id
            await s.commit()
            messages = compose(post, self._load_image(post.image_path))

        first_id: int | None = None
        poll_id: str | None = None
        try:
            for msg in messages:
                if msg.kind == "photo":
                    mid = await self.sender.send_photo(chat_id, msg.photo or b"", msg.text)
                elif msg.kind == "poll":
                    poll = msg.poll or {}
                    mid, poll_id = await self.sender.send_poll(
                        chat_id,
                        question=poll["question"],
                        options=list(poll["options"]),
                        quiz=bool(poll.get("quiz")),
                        correct_option_id=poll.get("correct_option_id"),
                        explanation=poll.get("explanation"),
                        is_anonymous=True,
                    )
                else:
                    mid = await self.sender.send_message(chat_id, msg.text or "")
                if first_id is None:
                    first_id = mid
                    await self._save_message_id(post_id, mid)
        except Exception as exc:
            return await self._on_failure(post_id, first_id, exc)

        async with self.repo.session() as s:
            post = await s.get(Post, post_id)
            assert post is not None
            post.message_id = first_id
            post.published_at = utcnow()
            await transition(s, post, PostStatus.PUBLISHED, "publisher", message_id=first_id)
            if poll_id:
                await self._attach_poll(s, post_id, poll_id)
            await s.commit()
        logger.info("Post #{} chiqarildi (chat {}, message {})", post_id, chat_id, first_id)
        if self.on_published:
            try:
                await self.on_published(post_id)
            except Exception:
                logger.exception("on_published xatosi")
        return True

    async def _save_message_id(self, post_id: int, mid: int) -> None:
        async with self.repo.session() as s:
            post = await s.get(Post, post_id)
            if post is not None:
                post.message_id = mid
                await s.commit()

    async def _attach_poll(self, s: object, post_id: int, poll_id: str) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession

        assert isinstance(s, AsyncSession)
        poll = (await s.execute(select(Poll).where(Poll.post_id == post_id))).scalar_one_or_none()
        if poll is not None:
            poll.telegram_poll_id = poll_id
            poll.closes_at = utcnow() + timedelta(hours=POLL_HOURS.get(poll.purpose, 24))

    async def _on_failure(self, post_id: int, first_id: int | None, exc: Exception) -> bool:
        err = mask_secrets(f"{type(exc).__name__}: {exc}")[:500]
        logger.warning("Post #{} yuborilmadi: {}", post_id, err)
        async with self.repo.session() as s:
            post = await s.get(Post, post_id)
            assert post is not None
            post.attempts += 1
            if first_id is not None:
                # Birinchi xabar ketdi — takror yubormaymiz (dublikat bo'lmasin)
                post.message_id = first_id
                post.published_at = utcnow()
                await transition(s, post, PostStatus.PUBLISHED, "publisher", partial=True, error=err)
                await s.commit()
                await self.notifier.notify(
                    f"⚠️ Post #{post_id} qisman chiqdi: {err}", key=f"partial:{post_id}"
                )
                return True
            if post.attempts >= MAX_ATTEMPTS:
                await transition(s, post, PostStatus.FAILED, "publisher", error=err)
                await s.commit()
                await self.repo.audit("publisher", "error", message=f"Post #{post_id} chiqmadi: {err}")
                await self.notifier.notify(
                    f"❌ Post #{post_id} {MAX_ATTEMPTS} urinishdan keyin chiqmadi: {err}",
                    key=f"failed:{post_id}",
                )
            else:
                await transition(s, post, PostStatus.SCHEDULED, "publisher", retry=post.attempts, error=err)
                await s.commit()
        return False

    async def _maybe_add_cta(self, post: Post) -> None:
        if self.runtime is None or post.kind not in CTA_KINDS:
            return
        every = int(await self.runtime.get("share_cta_every") or 0)
        if every <= 0:
            return
        counter = int(await self.repo.get_setting("cta_counter", 0)) + 1
        await self.repo.set_setting("cta_counter", counter)
        if counter % every != 0 or SHARE_CTA in post.text_html:
            return
        lines = post.text_html.rstrip().split("\n")
        if lines and lines[-1].startswith("👉"):
            new_text = "\n".join([*lines[:-1], SHARE_CTA, lines[-1]])
        else:
            new_text = post.text_html.rstrip() + "\n\n" + SHARE_CTA
        if post.image_path and visible_length(new_text) > CAPTION_LIMIT >= visible_length(post.text_html):
            return  # caption limitidan oshmasin
        post.text_html = new_text

    @staticmethod
    def _load_image(path: str | None) -> bytes | None:
        if not path:
            return None
        p = Path(path)
        try:
            return p.read_bytes() if p.is_file() else None
        except OSError:
            return None

    async def recover_inflight(self) -> int:
        """Qayta ishga tushganda PUBLISHING da qolgan postlarni tekshiradi — hech qachon qayta yubormaydi."""
        count = 0
        async with self.repo.session() as s:
            rows = (await s.execute(select(Post).where(Post.status == PostStatus.PUBLISHING))).scalars().all()
            failed: list[int] = []
            for post in rows:
                count += 1
                if post.message_id:
                    post.published_at = post.published_at or post.updated_at
                    await transition(s, post, PostStatus.PUBLISHED, "recovery")
                else:
                    await transition(s, post, PostStatus.FAILED, "recovery", reason="restart during publish")
                    failed.append(post.id)
            await s.commit()
        for pid in failed:
            await self.notifier.notify(
                f"⚠️ Post #{pid} yuborilayotganda bot to'xtab qoldi. "
                "Kanalni tekshiring: post chiqmagan bo'lsa, "
                "/queue orqali qayta rejalashtiring.",
                key=f"recover:{pid}",
            )
        return count

    async def publish_due(self, now: datetime | None = None) -> int:
        if self.runtime is not None and await self.runtime.paused():
            return 0
        now = now or utcnow()
        hours = int(await self.runtime.get("news_expiry_hours")) if self.runtime is not None else 6
        stale_before = now - timedelta(hours=hours)
        async with self.repo.session() as s:
            due = list(
                (
                    await s.execute(
                        select(Post)
                        .where(Post.status == PostStatus.SCHEDULED, Post.scheduled_at <= now)
                        .order_by(Post.scheduled_at, Post.id)
                    )
                ).scalars()
            )
            ids: list[int] = []
            for post in due:
                # Bot uzoq o'chiq turgan bo'lsa — eskirgan yangilik chiqarilmaydi
                if post.kind in EXPIRING_KINDS and post.scheduled_at and post.scheduled_at <= stale_before:
                    await transition(s, post, PostStatus.EXPIRED, "publisher", reason="stale on publish")
                else:
                    ids.append(post.id)
            await s.commit()
        published = 0
        for pid in ids:
            if await self.publish(pid):
                published += 1
        return published
