"""Kontent quvuri: saralash → yozish → tekshirish → rasm → (tasdiqlash) → navbat."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.ai.prompts import load_prompt
from app.ai.schemas import TipTopic, WriterOutput
from app.ai.types import Message
from app.bot.approval_view import send_for_approval
from app.collectors.dedupe import title_similarity
from app.collectors.extract import extract_text
from app.content.formatting import normalize_uz, sanitize_html
from app.content.schedule import plan_day
from app.content.templates import render_footer, telegram_post_link
from app.db.models import Post, Story
from app.pipeline.check import Checker
from app.pipeline.select import Selector
from app.pipeline.slots import next_free_slot
from app.pipeline.state import PostKind, PostStatus, transition
from app.pipeline.write import DraftResult, Writer, draft_with_checks
from app.utils.security import mask_secrets
from app.utils.timeutil import parse_hhmm, shift_out_of_quiet, to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

S = PostStatus
EXPIRING_KINDS = (PostKind.NEWS, PostKind.ALERT, PostKind.DIGEST)
SOURCE_TEXT_LIMIT = 12_000
MAX_STORY_ATTEMPTS = 2
IMAGE_MISSING_REASON = "🖼 Mos bepul rasm topilmadi — AI rasm (pullik) yoki rasmsiz chiqarish?"


def _is_url(text: str) -> bool:
    return text.strip().lower().startswith(("http://", "https://"))


class Pipeline:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock
        self.writer = Writer(ctx)
        self.checker = Checker(ctx)
        self.selector = Selector(ctx, clock=clock)

    @property
    def repo(self) -> Any:
        return self.ctx.repo

    # ------------------------------------------------------------------ slotlar

    async def prepare_slot(self, slot_time: str, scheduled_at: datetime) -> int | None:
        rt = self.ctx.runtime
        if await rt.paused() or await rt.publish_mode() == "manual":
            return None
        times = list(await rt.get("slot_times"))
        if slot_time not in times:
            return None  # sozlamadan olib tashlangan vaqt
        local = to_tz(scheduled_at, self.ctx.settings.tz)
        slot_key = f"{local.date().isoformat()}:{slot_time}"
        if await self._slot_taken(slot_key):
            return None
        categories = list(await rt.get("categories"))
        plan = plan_day(
            local.weekday(),
            times,
            categories,
            int(await rt.get("polls_per_week")),
            int(await rt.get("quizzes_per_week")),
        )
        kind = plan[times.index(slot_time)]
        tips_ok = "maslahat" in categories
        if kind in (PostKind.POLL, PostKind.QUIZ):
            svc = self.ctx.services.get("polls" if kind == PostKind.POLL else "quizzes")
            if svc is not None:
                result: int | None = await svc.create(None, scheduled_at=scheduled_at, slot=slot_key)
                return result
            kind = PostKind.NEWS
        if kind == PostKind.TIP:
            return await self.prepare_tip(scheduled_at, slot=slot_key)
        try:
            await self.selector.score_new()
        except Exception as exc:
            logger.warning("Saralashda xato (oldin baholanganlar ishlatiladi): {}", exc)
        for _ in range(MAX_STORY_ATTEMPTS):
            story, final_kind = await self._pick_for(kind)
            if story is None:
                break
            pid = await self.prepare_from_story(story.id, final_kind, scheduled_at, slot=slot_key)
            if pid is not None:
                return pid
        if kind in (PostKind.TOOL, PostKind.SITE) and tips_ok:
            return await self.prepare_tip(scheduled_at, slot=slot_key)
        await self.ctx.notifier.notify(
            f"ℹ️ {local:%d.%m %H:%M} slot uchun mos material topilmadi — post tayyorlanmadi.",
            key=f"noslot:{slot_key}",
        )
        return None

    async def _pick_for(self, kind: PostKind) -> tuple[Story | None, PostKind]:
        story = await self.selector.pick(kind)
        if story is None and kind in (PostKind.TOOL, PostKind.SITE):
            other = PostKind.SITE if kind == PostKind.TOOL else PostKind.TOOL
            story = await self.selector.pick(other)
            kind = other
        if story is not None and kind == PostKind.NEWS and story.category == "kiber":
            kind = PostKind.ALERT
        return story, kind

    async def _slot_taken(self, slot_key: str) -> bool:
        return bool(await self.repo.posts.count({"slot": slot_key, "status": {"$ne": S.REJECTED}}))

    # ------------------------------------------------------------------ story'dan post

    async def prepare_from_story(
        self,
        story_id: int | None,
        kind: PostKind | str,
        scheduled_at: datetime | None,
        *,
        slot: str | None = None,
        force_approval: bool = False,
        created_by: str = "ai",
        instructions: str | None = None,
    ) -> int | None:
        kind = PostKind(kind)
        story = await self.repo.stories.get(story_id)
        if story is None:
            return None
        await self.repo.stories.update(story_id, {"status": "used"})
        material = await self.story_material(story_id)
        pid = await self._new_post(
            kind,
            story_id=story.id,
            slot=slot,
            scheduled_at=scheduled_at,
            created_by=created_by,
            source_urls=material["urls"],
            score=story.score,
            extra={
                "category": story.category,
                "why_uz": story.why_uz,
                "risk_flags": list(story.risk_flags or []),
                "source_text": material["source_text"][:SOURCE_TEXT_LIMIT],
                "extra_allowed": material["extra_allowed"],
                "story_title": story.title,
                "source_name": material["source_name"],
            },
        )
        return await self._draft(pid, force_approval=force_approval, instructions=instructions)

    async def story_material(self, story_id: int | None) -> dict[str, Any]:
        """Story uchun manba havolalari, qo'shimcha ruxsat etilgan havolalar, manba nomi va matni."""
        rows = await self._source_rows(story_id)
        urls: list[str] = []
        extra_allowed: list[str] = []
        for art, _src in rows:
            if art.url not in urls:
                urls.append(art.url)
            extra = art.extra or {}
            for key in ("cisa_url", "homepage", "hn_url"):
                if extra.get(key):
                    extra_allowed.append(str(extra[key]))
        return {
            "urls": urls,
            "extra_allowed": extra_allowed,
            "source_name": next((src.name for _a, src in rows if src is not None), None),
            "source_text": await self._source_text(rows),
        }

    async def _source_rows(self, story_id: int | None) -> list[Any]:
        """Story maqolalari va manbalari (ishonchli manba birinchi)."""
        articles = await self.repo.articles.find({"story_id": story_id}, sort=[("_id", 1)])
        ids = list({a.source_id for a in articles if a.source_id is not None})
        sources = {s.id: s for s in await self.repo.sources.find({"_id": {"$in": ids}})}
        rows = [(a, sources.get(a.source_id)) for a in articles]
        rows.sort(
            key=lambda r: -(r[1].trust if r[1] is not None else -1)
        )  # barqaror: ishonchli manba birinchi
        return rows

    async def _source_text(self, rows: Sequence[Any]) -> str:
        parts: list[str] = []
        for art, src in rows[:6]:
            name = src.name if src is not None else "?"
            parts.append(f"[{name}] {art.title}\n{art.summary or ''}".strip())
        main = None
        if rows and self.ctx.http is not None:
            main = await extract_text(self.ctx.http, rows[0][0].url)
        if main:
            parts.append("Asosiy maqola matni:\n" + main)
        return "\n\n".join(parts)[:SOURCE_TEXT_LIMIT]

    async def _new_post(
        self,
        kind: PostKind,
        *,
        story_id: int | None,
        slot: str | None,
        scheduled_at: datetime | None,
        created_by: str,
        source_urls: list[str],
        score: int | None,
        extra: dict[str, Any],
    ) -> int:
        post = await self.repo.posts.insert(
            Post(
                kind=kind,
                status=S.NEW,
                story_id=story_id,
                slot=slot,
                scheduled_at=scheduled_at,
                publish_key=uuid.uuid4().hex,
                created_by=created_by,
                source_urls=source_urls,
                score=score,
                extra=extra,
                created_at=self.clock(),
                updated_at=self.clock(),
            )
        )
        await transition(self.repo, post, S.SELECTED, created_by)
        await self.repo.posts.save(post)
        return post.id  # type: ignore[return-value]

    async def _draft(
        self,
        post_id: int,
        *,
        force_approval: bool = False,
        instructions: str | None = None,
        previous: WriterOutput | None = None,
    ) -> int | None:
        post = await self.ctx.repo.get_post(post_id)
        if post is None:
            return None
        extra = post.extra or {}
        kind = PostKind(post.kind)
        try:
            res: DraftResult = await draft_with_checks(
                self.writer,
                self.checker,
                kind,
                source_text=extra.get("source_text", ""),
                story_title=extra.get("story_title") or post.title_short or "",
                source_urls=post.source_urls or [],
                source_name=extra.get("source_name"),
                has_image=self.ctx.services.get("images") is not None,
                risk_flags=extra.get("risk_flags", []),
                instructions=instructions,
                extra_allowed=extra.get("extra_allowed", []),
            )
        except Exception as exc:
            await self._mark_failed(post_id, exc)
            return None
        report = res.report
        admin_flow = force_approval or post.created_by == "admin"
        post = await self.repo.posts.get(post_id)
        assert post is not None
        await self._to_drafted(post)
        if report.verdict == "reject" and not admin_flow:
            post.check_report = report.to_dict()
            await transition(self.repo, post, S.REJECTED, "checker", issues=report.all_issues()[:5])
            await self.repo.posts.save(post)
            if post.story_id:
                await self.repo.stories.update(post.story_id, {"status": "rejected"})
            logger.info("Post #{} tekshiruvdan o'tmadi va rad etildi", post_id)
            return None
        out = res.output
        post.text_html = out.text_html
        post.title_short = out.title_short
        post.hashtags = out.hashtags
        post.image_prompt = out.image_prompt_en
        if out.image_query_en:
            post.extra = {**(post.extra or {}), "image_query": out.image_query_en}
        await transition(self.repo, post, S.CHECKED, "checker", verdict=report.verdict, rounds=res.rounds)
        if report.verdict == "reject":
            report.needs_approval = True
            report.add_reason("Tekshiruvchi rad etdi — diqqat bilan koʻrib chiqing")
        post.check_report = report.to_dict()
        post.needs_approval = report.needs_approval or admin_flow
        post.approval_reason = report.approval_reason
        await self.repo.posts.save(post)
        await self._make_image(post_id)
        await self._image_gate(post_id)
        await self.after_check(post_id)
        return post_id

    async def _mark_failed(self, post_id: int, exc: BaseException) -> None:
        """AI xatosi tufayli qoralama tayyorlanmadi: post FAILED, adminga xabar (post osilib qolmaydi)."""
        err = mask_secrets(f"{type(exc).__name__}: {exc}")[:400]
        logger.warning("Post #{} qoralamasi tayyorlanmadi: {}", post_id, err)
        post = await self.repo.posts.get(post_id)
        if post is not None and post.status not in (S.PUBLISHED, S.REJECTED, S.EXPIRED, S.FAILED):
            await transition(self.repo, post, S.FAILED, "pipeline", error=err)
            await self.repo.posts.save(post)
        await self.ctx.repo.audit("pipeline", "error", message=f"Post #{post_id}: {err}")
        await self.ctx.notifier.notify(
            f"⚠️ Post #{post_id} qoralamasi tayyorlanmadi: {err}", key=f"draft-fail:{post_id}"
        )

    async def _to_drafted(self, post: Post) -> None:
        if post.status == S.SCHEDULED:
            await transition(self.repo, post, S.PENDING_APPROVAL, "pipeline")
        if post.status in (S.SELECTED, S.CHECKED, S.PENDING_APPROVAL):
            await transition(self.repo, post, S.DRAFTED, "writer")

    async def _make_image(self, post_id: int, *, fresh: bool = False) -> None:
        images = self.ctx.services.get("images")
        if images is None:
            return
        try:
            await images.make_for_post(post_id, fresh=fresh)
        except Exception as exc:
            logger.warning("Post #{} uchun rasm tayyorlanmadi: {}", post_id, exc)

    async def _image_gate(self, post_id: int) -> None:
        """Bepul rasm topilmadi: post auto rejimda ham admin qaroriga keladi (AI rasm — pullik)."""
        post = await self.repo.posts.get(post_id)
        if post is None or (post.extra or {}).get("image_status") != "missing":
            return
        post.extra = {**post.extra, "image_gate": not post.needs_approval}
        post.needs_approval = True
        if IMAGE_MISSING_REASON not in (post.approval_reason or ""):
            post.approval_reason = "; ".join(filter(None, [post.approval_reason, IMAGE_MISSING_REASON]))
        await self.repo.posts.save(post)

    async def _schedule_now_or_slot(self, post: Post, actor: str, **details: Any) -> datetime:
        """Kelajakdagi vaqti saqlanadi, aks holda keyingi boʻsh slot; post SCHEDULED boʻladi."""
        if post.scheduled_at is None or post.scheduled_at <= self.clock():
            post.scheduled_at, slot = await next_free_slot(self.ctx)
            if slot:
                post.slot = slot
        await transition(self.repo, post, S.SCHEDULED, actor, **details)
        await self.repo.posts.save(post)
        return post.scheduled_at

    @staticmethod
    def _drop_image_reason(post: Post) -> None:
        parts = [p for p in (post.approval_reason or "").split("; ") if p and p != IMAGE_MISSING_REASON]
        post.approval_reason = "; ".join(parts) or None

    async def use_ai_image(self, post_id: int) -> str:
        """Admin ruxsati bilan AI rasm: auto rejimda (boshqa sabab boʻlmasa) rejaga, aks holda tasdiqqa."""
        # Atomik: tugma ikki marta bosilsa ham pullik rasm bir marta yaratiladi
        if not await self.repo.posts.cas(
            post_id,
            {"status": S.PENDING_APPROVAL, "extra.image_status": "missing"},
            {"extra.image_status": "generating"},
        ):
            return "⏳ Rasm allaqachon tayyorlangan yoki tayyorlanmoqda"
        images = self.ctx.services.get("images")
        try:
            path = await images.make_for_post(post_id, force_ai=True) if images is not None else None
        except Exception as exc:
            logger.warning("Post #{} uchun AI rasm yaratilmadi: {}", post_id, mask_secrets(str(exc)))
            path = None
        post = await self.repo.posts.get(post_id)
        if post is None or post.status != S.PENDING_APPROVAL:
            return "Post topilmadi yoki holati oʻzgargan"
        if path is None:
            await self.repo.posts.update(post_id, {"extra.image_status": "missing"})
            return "❌ AI rasm yaratilmadi — /logs ni koʻring"
        self._drop_image_reason(post)
        auto = await self.ctx.runtime.publish_mode() == "auto"
        if auto and (post.extra or {}).get("image_gate") and post.created_by == "ai":
            post.needs_approval = False
            when = await self._schedule_now_or_slot(post, "admin", image="ai")
            return f"🎨 Rasm tayyor — post {to_tz(when, self.ctx.settings.tz):%d.%m %H:%M} ga qoʻyildi"
        await self.repo.posts.save(post)
        await send_for_approval(self.ctx, post_id)
        return "🎨 Rasm tayyor — postni koʻrib chiqing"

    async def publish_without_image(self, post_id: int) -> str:
        """Admin qarori: post rasmsiz chiqadi (kelajakdagi vaqtida yoki keyingi boʻsh slotda)."""
        post = await self.repo.posts.get(post_id)
        if post is None or post.status != S.PENDING_APPROVAL:
            return "Post topilmadi yoki holati oʻzgargan"
        extra = {**(post.extra or {}), "image_status": "none"}
        extra.pop("image_credit", None)
        post.extra, post.image_path = extra, None
        self._drop_image_reason(post)
        when = await self._schedule_now_or_slot(post, "admin", image="none")
        return f"📝 Rasmsiz — {to_tz(when, self.ctx.settings.tz):%d.%m %H:%M} ga qoʻyildi"

    async def after_check(self, post_id: int) -> None:
        mode = await self.ctx.runtime.publish_mode()
        post = await self.repo.posts.get(post_id)
        if post is None or post.status != S.CHECKED:
            return
        if mode == "auto" and not post.needs_approval and post.created_by == "ai":
            post.scheduled_at = post.scheduled_at or self.clock()
            await transition(self.repo, post, S.SCHEDULED, "pipeline", mode=mode)
            await self.repo.posts.save(post)
            return
        await transition(self.repo, post, S.PENDING_APPROVAL, "pipeline", mode=mode)
        await self.repo.posts.save(post)
        await send_for_approval(self.ctx, post_id)

    # ------------------------------------------------------------------ maslahat, admin, dayjest

    async def prepare_tip(
        self,
        scheduled_at: datetime | None,
        *,
        slot: str | None = None,
        topic: str | None = None,
        created_by: str = "ai",
        force_approval: bool = False,
    ) -> int | None:
        angle = ""
        if topic is None:
            recent = await self._recent_titles(PostKind.TIP, days=60)
            res = await self.ctx.router.complete(
                "writer",
                [
                    Message("system", load_prompt("tip_topic"), cache=True),
                    Message(
                        "user", "Oxirgi maslahatlar: " + "; ".join(recent[:30]) if recent else "Hali yo'q."
                    ),
                ],
                schema=TipTopic,
                temperature=0.8,
                max_tokens=300,
            )
            topic, angle = res.parsed.topic, res.parsed.angle
        source_text = (
            f"Mavzu: {topic}\nYoʻnalish: {angle or '—'}\n"
            "Umumiy qabul qilingan, tekshiriladigan, amaliy maslahat yoz. Aniq qadamlar ber."
        )
        pid = await self._new_post(
            PostKind.TIP,
            story_id=None,
            slot=slot,
            scheduled_at=scheduled_at,
            created_by=created_by,
            source_urls=[],
            score=None,
            extra={"category": "maslahat", "source_text": source_text, "story_title": topic},
        )
        return await self._draft(pid, force_approval=force_approval)

    async def _recent_titles(self, kind: PostKind, days: int) -> list[str]:
        rows = await self.repo.posts.find(
            {"kind": kind, "created_at": {"$gte": self.clock() - timedelta(days=days)}}
        )
        return [p.title_short for p in rows if p.title_short]

    async def prepare_from_admin(self, text: str, instructions: str | None = None) -> int | None:
        text = text.strip()
        if _is_url(text):
            url = text.split()[0]
            body = await extract_text(self.ctx.http, url) if self.ctx.http is not None else None
            if not body:
                raise ValueError("Havoladan maqola matnini olib boʻlmadi")
            pid = await self._new_post(
                PostKind.NEWS,
                story_id=None,
                slot=None,
                scheduled_at=None,
                created_by="admin",
                source_urls=[url],
                score=None,
                extra={"category": "yangilik", "source_text": body[:SOURCE_TEXT_LIMIT], "story_title": url},
            )
            return await self._draft(pid, force_approval=True, instructions=instructions)
        story = await self._find_story(text)
        if story is not None:
            kind = PostKind.ALERT if story.category == "kiber" else PostKind.NEWS
            return await self.prepare_from_story(
                story.id, kind, None, force_approval=True, created_by="admin", instructions=instructions
            )
        return await self.prepare_tip(None, topic=text, created_by="admin", force_approval=True)

    async def _find_story(self, topic: str) -> Story | None:
        stories = await self.repo.stories.find(
            {
                "first_seen": {"$gte": self.clock() - timedelta(hours=72)},
                "status": {"$in": ["new", "filtered", "scored"]},
            }
        )
        best = max(stories, key=lambda st: title_similarity(topic, st.title), default=None)
        if best is not None and title_similarity(topic, best.title) >= 60:
            return best
        return None

    # ------------------------------------------------------------------ admin tahriri

    async def rewrite(self, post_id: int, instruction: str | None = None) -> int | None:
        post = await self.ctx.repo.get_post(post_id)
        if post is None or post.status not in (S.PENDING_APPROVAL, S.SCHEDULED, S.CHECKED):
            raise ValueError("Bu postni hozir qayta yozib boʻlmaydi")
        return await self._draft(
            post_id, force_approval=True, instructions=instruction or "Qaytadan, yaxshiroq yoz"
        )

    async def replace_text(self, post_id: int, html: str) -> None:
        text = normalize_uz(sanitize_html(html))
        footer = render_footer(self.ctx.settings.channel_username)
        if footer and footer not in text:
            text = text.rstrip() + "\n" + footer
        post = await self.repo.posts.get(post_id)
        if post is None or post.status not in (S.PENDING_APPROVAL, S.SCHEDULED, S.CHECKED):
            raise ValueError("Bu postni hozir tahrirlab boʻlmaydi")
        await self._to_drafted(post)
        post.text_html = text
        await transition(self.repo, post, S.CHECKED, "admin")
        post.check_report = {"verdict": "admin", "issues": [], "code_issues": []}
        post.needs_approval = True
        await transition(self.repo, post, S.PENDING_APPROVAL, "admin")
        await self.repo.posts.save(post)
        await send_for_approval(self.ctx, post_id)

    async def regenerate_image(self, post_id: int) -> None:
        await self._make_image(post_id, fresh=True)
        await send_for_approval(self.ctx, post_id)

    async def prepare_custom(
        self,
        kind: PostKind | str,
        *,
        source_text: str,
        story_title: str,
        category: str,
        scheduled_at: datetime | None = None,
        force_approval: bool = False,
        created_by: str = "ai",
    ) -> int | None:
        """Manbasiz maxsus post (masalan, haftalik savol-javob)."""
        pid = await self._new_post(
            PostKind(kind),
            story_id=None,
            slot=None,
            scheduled_at=scheduled_at,
            created_by=created_by,
            source_urls=[],
            score=None,
            extra={
                "category": category,
                "source_text": source_text[:SOURCE_TEXT_LIMIT],
                "story_title": story_title,
            },
        )
        return await self._draft(pid, force_approval=force_approval)

    # ------------------------------------------------------------------ haftalik dayjest

    def post_link(self, post: Post) -> str | None:
        if not post.message_id or not post.chat_id:
            return None
        return telegram_post_link(
            post.chat_id,
            post.message_id,
            channel_id=self.ctx.settings.channel_id,
            username=self.ctx.settings.channel_username,
        )

    async def prepare_digest(self, scheduled_at: datetime | None, *, min_posts: int = 3) -> int | None:
        now = self.clock()
        posts = await self.repo.posts.find(
            {
                "status": S.PUBLISHED,
                "published_at": {"$gte": now - timedelta(days=7)},
                "kind": {"$nin": [PostKind.DIGEST, PostKind.POLL, PostKind.QUIZ, PostKind.QA]},
            }
        )
        metrics = self.ctx.services.get("metrics")
        engagement: dict[int, float] = {}
        if metrics is not None:
            engagement = await metrics.engagement_by_post([p.id for p in posts])
        posts.sort(key=lambda p: (engagement.get(p.id, 0.0), p.score or 0), reverse=True)
        items = [
            {
                "title": p.title_short,
                "kind": p.kind,
                "url": link,
                "engagement": round(engagement.get(p.id, 0.0), 1),
            }
            for p in posts
            if (link := self.post_link(p))
        ][:7]
        if len(items) < min_posts:
            await self.ctx.notifier.notify("ℹ️ Haftalik dayjest uchun postlar yetarli emas.", key="digest-few")
            return None
        local = to_tz(scheduled_at or now, self.ctx.settings.tz)
        pid = await self._new_post(
            PostKind.DIGEST,
            story_id=None,
            slot=f"{local.date().isoformat()}:digest",
            scheduled_at=scheduled_at,
            created_by="ai",
            source_urls=[],
            score=None,
            extra={
                "category": "dayjest",
                "source_text": json.dumps(items, ensure_ascii=False),
                "story_title": "Hafta dayjesti",
                "extra_allowed": ["https://t.me/"],
            },
        )
        return await self._draft(pid)

    # ------------------------------------------------------------------ muddat va shoshilinch

    async def expire_stale(self, now: datetime | None = None) -> int:
        now = now or self.clock()
        rt = self.ctx.runtime
        expiry = timedelta(hours=int(await rt.get("news_expiry_hours")))
        timeout = timedelta(minutes=int(await rt.get("approval_timeout_min")))
        action = await rt.get("approval_timeout_action")
        changed = 0
        rows = await self.repo.posts.find({"status": {"$in": [S.PENDING_APPROVAL, S.SCHEDULED]}})
        for post in rows:
            if post.kind in EXPIRING_KINDS:
                # Kelajakka (masalan, tungi shoshilinch → 07:30) qo'yilgan post vaqtidan oldin eskirmaydi
                ref = max(post.created_at, post.scheduled_at) if post.scheduled_at else post.created_at
                if ref <= now - expiry:
                    await transition(self.repo, post, S.EXPIRED, "scheduler", reason="news expired")
                    await self.repo.posts.save(post)
                    changed += 1
                    continue
            if (
                action == "publish"
                and post.status == S.PENDING_APPROVAL
                and not post.needs_approval
                and post.created_by == "ai"
                and post.approval_sent_at is not None
                and post.approval_sent_at <= now - timeout
            ):
                if post.scheduled_at is None or post.scheduled_at < now:
                    post.scheduled_at = now
                await transition(self.repo, post, S.SCHEDULED, "scheduler", reason="approval timeout")
                await self.repo.posts.save(post)
                changed += 1
        return changed

    async def handle_breaking(self, now: datetime | None = None) -> int | None:
        now = now or self.clock()
        rt = self.ctx.runtime
        if await rt.paused() or await rt.publish_mode() == "manual":
            return None
        if "kiber" not in await rt.get("categories"):
            return None  # kiberxavfsizlik turkumi o'chirilgan
        try:
            await self.selector.score_new(source_categories=("kiber",))
        except Exception as exc:
            logger.warning("Shoshilinch saralashda xato: {}", exc)
        candidates = await self.selector.breaking_candidates(int(await rt.get("breaking_min_score")), now=now)
        if not candidates:
            return None
        quiet = await rt.get("quiet")
        scheduled = shift_out_of_quiet(
            now,
            parse_hhmm(quiet["start"]),
            parse_hhmm(quiet["end"]),
            parse_hhmm(quiet["resume"]),
            self.ctx.settings.tz,
        )
        key = f"{to_tz(scheduled, self.ctx.settings.tz).date().isoformat()}:urgent"
        if await self._slot_taken(key):
            return None
        pid = await self.prepare_from_story(candidates[0].id, PostKind.ALERT, scheduled, slot=key)
        if pid is not None:
            await self.ctx.notifier.notify(
                f"🚨 Shoshilinch kiber xabar qoralamasi tayyor: #{pid}", key=f"urgent:{pid}"
            )
        return pid
