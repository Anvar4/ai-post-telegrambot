"""Rasm bosqichi: bepul rasm qidirish yoki 2-model (AI) rasm → vision tekshiruv → Pillow brend shabloni."""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import TYPE_CHECKING

from loguru import logger
from PIL import Image

from app.ai.prompts import load_prompt
from app.ai.schemas import ImageReview
from app.ai.types import Message
from app.content.brand_image import canvas_size, render_cover
from app.content.templates import KIND_LABEL
from app.db.models import Post
from app.images.search import ImageSearch
from app.pipeline.state import PostKind

if TYPE_CHECKING:
    from app.context import AppContext

NO_IMAGE_KINDS = frozenset({PostKind.POLL, PostKind.QUIZ})
REVIEW_MAX_SIDE = 768
QUERY_WORDS = 5
IMAGE_MODES = ("search_then_ask", "ai", "none")


def _thumbnail(data: bytes) -> bytes:
    img: Image.Image = Image.open(BytesIO(data)).convert("RGB")
    img.thumbnail((REVIEW_MAX_SIDE, REVIEW_MAX_SIDE))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def search_query(post: Post) -> str:
    """Fotobank soʻrovi: yozuvchining `image_query_en` i, boʻlmasa rasm promptining boshi."""
    query = str((post.extra or {}).get("image_query") or "").strip()
    if not query:
        query = " ".join((post.image_prompt or "").replace(",", " ").split()[:QUERY_WORDS])
    return query


class ImageStage:
    def __init__(self, ctx: AppContext, *, search: ImageSearch | None = None) -> None:
        self.ctx = ctx
        self.search = search

    async def make_for_post(self, post_id: int, *, force_ai: bool = False, fresh: bool = False) -> str | None:
        """Rasm rejimiga qarab: qidirish (topilmasa `image_status=missing`), AI yoki rasmsiz.

        `fresh` — "Boshqa rasm" tugmasi: oldingi tanlov (rasm yoki "rasmsiz") e'tiborga olinmaydi.
        """
        post = await self.ctx.repo.get_post(post_id)
        if post is None or post.kind in NO_IMAGE_KINDS:
            return None
        mode = "ai" if force_ai else str(await self.ctx.runtime.get("image_mode"))
        if mode == "none":
            return None
        if mode == "search_then_ask":
            return await self._from_search(post, fresh=fresh)
        kind = PostKind(post.kind)
        topic = post.image_prompt or post.title_short or "technology news"
        data = await self.make(title=post.title_short or "", category=KIND_LABEL.get(kind, ""), topic=topic)
        if data is None:
            return None
        path = await self._save(post_id, data)
        extra = {**(post.extra or {}), "image_status": "ai"}
        extra.pop("image_credit", None)
        await self.ctx.repo.posts.update(post_id, {"image_path": path, "extra": extra})
        return path

    async def _save(self, post_id: int, data: bytes) -> str:
        folder = self.ctx.settings.data_path / "images"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{post_id}.png"
        await asyncio.to_thread(path.write_bytes, data)
        return str(path)

    async def _from_search(self, post: Post, *, fresh: bool = False) -> str | None:
        extra = dict(post.extra or {})
        status = extra.get("image_status")
        if not fresh:
            # Qayta yozishda rasm qarori saqlanadi (yana soʻralmaydi, pul sarflanmaydi)
            if status in ("found", "ai") and post.image_path:
                return post.image_path
            if status == "none":
                return None
        seen = list(extra.get("image_seen", []))
        query = search_query(post)
        topic = post.image_prompt or query
        review = await self.ctx.runtime.get("image_review") and self.ctx.router.has("editor")

        async def accept(data: bytes) -> bool:
            return await self._review_ok(data, topic) if review else True

        found = None
        if self.search is not None and query:
            found = await self.search.find(query, exclude=seen, accept=accept)
        if found is None:
            if post.image_path and extra.get("image_status") in ("found", "ai"):
                return None  # boshqa mos rasm yoʻq — oldingisi qoladi
            extra["image_status"] = "missing"
            await self.ctx.repo.posts.update(post.id, {"image_path": None, "extra": extra})  # type: ignore[arg-type]
            return None
        cover = await self._cover(found.data, post)
        if cover is None:
            return None
        path = await self._save(post.id, cover)  # type: ignore[arg-type]
        extra.update(
            image_status="found",
            image_credit=found.credit_html(),
            image_seen=[*seen, found.candidate.source_id],
        )
        await self.ctx.repo.posts.update(post.id, {"image_path": path, "extra": extra})  # type: ignore[arg-type]
        return path

    async def _cover(self, base: bytes, post: Post) -> bytes | None:
        try:
            return await asyncio.to_thread(
                render_cover,
                base,
                title=post.title_short or "",
                category=KIND_LABEL.get(PostKind(post.kind), ""),
                username=self.ctx.settings.channel_username,
                size=canvas_size(self.ctx.settings.image_size),
            )
        except Exception as exc:
            logger.warning("Topilgan rasmni shablonga joylab boʻlmadi: {}", exc)
            return None

    async def make(self, *, title: str, category: str, topic: str) -> bytes | None:
        prompt = load_prompt("image", topic=topic)
        size = self.ctx.settings.image_size
        base = await self.ctx.router.image(prompt, size=size)
        if base is not None and await self.ctx.runtime.get("image_review") and self.ctx.router.has("editor"):
            if not await self._review_ok(base, topic):
                logger.info("Rasm tekshiruvdan o'tmadi — bitta qayta generatsiya")
                base = await self.ctx.router.image(prompt + "\nSimpler, cleaner composition.", size=size)
        username = self.ctx.settings.channel_username
        canvas = canvas_size(size)
        if base is not None:
            try:
                return await asyncio.to_thread(
                    render_cover, base, title=title, category=category, username=username, size=canvas
                )
            except Exception as exc:
                logger.warning("AI rasmni shablonga joylab bo'lmadi, brend fon ishlatiladi: {}", exc)
        try:
            return await asyncio.to_thread(
                render_cover, None, title=title, category=category, username=username, size=canvas
            )
        except Exception as exc:
            logger.error("Brend rasm ham chizilmadi — post rasmsiz chiqadi: {}", exc)
            return None

    async def _review_ok(self, image: bytes, topic: str) -> bool:
        try:
            thumb = await asyncio.to_thread(_thumbnail, image)
            res = await self.ctx.router.complete(
                "editor",
                [
                    Message("system", load_prompt("image_review", topic=topic)),
                    Message("user", "Rasmni baholang.", images=[thumb]),
                ],
                schema=ImageReview,
                temperature=0.0,
                max_tokens=200,
            )
            return bool(res.parsed.ok)
        except Exception as exc:
            logger.debug("Rasm tekshiruvi o'tkazib yuborildi: {}", exc)
            return True
