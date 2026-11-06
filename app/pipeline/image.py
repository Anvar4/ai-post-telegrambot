"""Rasm bosqichi: 2-model rasm → (ixtiyoriy vision tekshiruv) → Pillow brend shabloni; zaxira — brend fon."""

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
from app.pipeline.state import PostKind

if TYPE_CHECKING:
    from app.context import AppContext

NO_IMAGE_KINDS = frozenset({PostKind.POLL, PostKind.QUIZ})
REVIEW_MAX_SIDE = 768


def _thumbnail(data: bytes) -> bytes:
    img: Image.Image = Image.open(BytesIO(data)).convert("RGB")
    img.thumbnail((REVIEW_MAX_SIDE, REVIEW_MAX_SIDE))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class ImageStage:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def make_for_post(self, post_id: int) -> str | None:
        post = await self.ctx.repo.get_post(post_id)
        if post is None or post.kind in NO_IMAGE_KINDS:
            return None
        kind = PostKind(post.kind)
        topic = post.image_prompt or post.title_short or "technology news"
        data = await self.make(title=post.title_short or "", category=KIND_LABEL.get(kind, ""), topic=topic)
        if data is None:
            return None
        folder = self.ctx.settings.data_path / "images"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{post_id}.png"
        await asyncio.to_thread(path.write_bytes, data)
        await self.ctx.repo.posts.update(post_id, {"image_path": str(path)})
        return str(path)

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
