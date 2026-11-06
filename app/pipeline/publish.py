"""Nashr qiluvchi: idempotent (atomik CAS), DRY_RUN himoyasi, 3 urinish, qayta ishga tushganda tiklash."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.content.formatting import visible_length
from app.content.limits import CAPTION_LIMIT
from app.content.templates import SHARE_CTA, telegram_post_link
from app.db.models import Post
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
        post = await self.repo.posts.get(post_id)
        if post is None:
            return False
        if post.status == PostStatus.PUBLISHED:
            return True
        if post.status != PostStatus.SCHEDULED:
            return False
        # Atomik: faqat bitta jarayon SCHEDULED -> PUBLISHING o'tkaza oladi (ikki marta chiqmaydi)
        if not await self.repo.posts.cas(
            post_id, {"status": PostStatus.SCHEDULED}, {"status": PostStatus.PUBLISHING, "chat_id": chat_id}
        ):
            return False
        await self.repo.audit(
            "publisher",
            "post.status",
            post_id=post_id,
            **{"from": "SCHEDULED"},
            to="PUBLISHING",
            chat_id=chat_id,
        )
        post.status, post.chat_id = PostStatus.PUBLISHING.value, chat_id
        await self._maybe_add_cta(post)
        await self.repo.posts.update(post_id, {"text_html": post.text_html})
        messages = compose(post, self._load_image(post.image_path))

        first_id: int | None = None
        last_id: int | None = None
        poll_id: str | None = None
        try:
            for msg in messages:
                if msg.kind == "photo":
                    mid = await self.sender.send_photo(chat_id, msg.photo or b"", msg.text)
                elif msg.kind == "media":
                    media = msg.media or {}
                    mid = await self.sender.send_media(chat_id, media["type"], media["file_id"], msg.text)
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
                last_id = mid
                if first_id is None:
                    first_id = mid
                    await self.repo.posts.update(post_id, {"message_id": mid})
        except Exception as exc:
            return await self._on_failure(post_id, first_id, exc)

        post = await self.repo.posts.get(post_id)
        assert post is not None
        post.message_id = first_id
        post.published_at = utcnow()
        await transition(self.repo, post, PostStatus.PUBLISHED, "publisher", message_id=first_id)
        await self.repo.posts.save(post)
        if poll_id:
            await self._attach_poll(post_id, poll_id)
        elif first_id is not None and last_id is not None:
            await self._add_share_button(post, chat_id, first_id, last_id)
        logger.info("Post #{} chiqarildi (chat {}, message {})", post_id, chat_id, first_id)
        if self.on_published:
            try:
                await self.on_published(post_id)
            except Exception:
                logger.exception("on_published xatosi")
        return True

    async def _add_share_button(self, post: Post, chat_id: int, first_id: int, last_id: int) -> None:
        """Oxirgi xabarga "📤 Ulashish" tugmasi (postning birinchi xabariga havola); xato nashrni buzmaydi."""
        if self.runtime is None or not await self.runtime.get("share_button"):
            return
        link = telegram_post_link(
            chat_id,
            first_id,
            channel_id=self.settings.channel_id,
            username=self.settings.channel_username,
        )
        from app.bot.keyboards import share_keyboard

        try:
            await self.sender.edit_reply_markup(
                chat_id, last_id, share_keyboard(link, post.title_short or "")
            )
        except Exception as exc:
            logger.warning("Post #{} ga ulashish tugmasi qoʻshilmadi: {}", post.id, exc)

    async def _attach_poll(self, post_id: int, poll_id: str) -> None:
        poll = await self.repo.polls.find_one({"post_id": post_id})
        if poll is not None:
            await self.repo.polls.update(
                poll.id,  # type: ignore[arg-type]
                {
                    "telegram_poll_id": poll_id,
                    "closes_at": utcnow() + timedelta(hours=POLL_HOURS.get(poll.purpose, 24)),
                },
            )

    async def _on_failure(self, post_id: int, first_id: int | None, exc: Exception) -> bool:
        err = mask_secrets(f"{type(exc).__name__}: {exc}")[:500]
        logger.warning("Post #{} yuborilmadi: {}", post_id, err)
        post = await self.repo.posts.get(post_id)
        assert post is not None
        post.attempts += 1
        if first_id is not None:
            # Birinchi xabar ketdi — takror yubormaymiz (dublikat bo'lmasin)
            post.message_id = first_id
            post.published_at = utcnow()
            await transition(self.repo, post, PostStatus.PUBLISHED, "publisher", partial=True, error=err)
            await self.repo.posts.save(post)
            await self.notifier.notify(f"⚠️ Post #{post_id} qisman chiqdi: {err}", key=f"partial:{post_id}")
            return True
        if post.attempts >= MAX_ATTEMPTS:
            await transition(self.repo, post, PostStatus.FAILED, "publisher", error=err)
            await self.repo.posts.save(post)
            await self.repo.audit("publisher", "error", message=f"Post #{post_id} chiqmadi: {err}")
            await self.notifier.notify(
                f"❌ Post #{post_id} {MAX_ATTEMPTS} urinishdan keyin chiqmadi: {err}", key=f"failed:{post_id}"
            )
        else:
            await transition(
                self.repo, post, PostStatus.SCHEDULED, "publisher", retry=post.attempts, error=err
            )
            await self.repo.posts.save(post)
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
        rows = await self.repo.posts.find({"status": PostStatus.PUBLISHING})
        failed: list[int] = []
        for post in rows:
            if post.message_id:
                post.published_at = post.published_at or post.updated_at
                await transition(self.repo, post, PostStatus.PUBLISHED, "recovery")
            else:
                await transition(
                    self.repo, post, PostStatus.FAILED, "recovery", reason="restart during publish"
                )
                failed.append(post.id)  # type: ignore[arg-type]
            await self.repo.posts.save(post)
        for pid in failed:
            await self.notifier.notify(
                f"⚠️ Post #{pid} yuborilayotganda bot to'xtab qoldi. "
                "Kanalni tekshiring: post chiqmagan bo'lsa, "
                "/queue orqali qayta rejalashtiring.",
                key=f"recover:{pid}",
            )
        return len(rows)

    async def publish_due(self, now: datetime | None = None) -> int:
        if self.runtime is not None and await self.runtime.paused():
            return 0
        now = now or utcnow()
        hours = int(await self.runtime.get("news_expiry_hours")) if self.runtime is not None else 6
        stale_before = now - timedelta(hours=hours)
        due = await self.repo.posts.find(
            {"status": PostStatus.SCHEDULED, "scheduled_at": {"$lte": now}},
            sort=[("scheduled_at", 1), ("_id", 1)],
        )
        ids: list[int] = []
        for post in due:
            # Bot uzoq o'chiq turgan bo'lsa — eskirgan yangilik chiqarilmaydi
            if post.kind in EXPIRING_KINDS and post.scheduled_at and post.scheduled_at <= stale_before:
                await transition(self.repo, post, PostStatus.EXPIRED, "publisher", reason="stale on publish")
                await self.repo.posts.save(post)
            else:
                ids.append(post.id)  # type: ignore[arg-type]
        published = 0
        for pid in ids:
            if await self.publish(pid):
                published += 1
        return published
