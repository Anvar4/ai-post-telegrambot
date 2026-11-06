"""fal.ai REST mijozi (sinxron `fal.run` endpoint)."""

from __future__ import annotations

import httpx

from app.ai.types import aspect_ratio

_SIZES = {"1:1": "square_hd", "16:9": "landscape_16_9", "9:16": "portrait_16_9"}


class FalImageClient:
    provider = "fal"

    def __init__(self, api_key: str, model: str | None, *, http: httpx.AsyncClient) -> None:
        self.model = model or "fal-ai/flux/schnell"
        self._key = api_key
        self._http = http

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        r = await self._http.post(
            f"https://fal.run/{self.model}",
            headers={"Authorization": f"Key {self._key}"},
            json={"prompt": prompt, "image_size": _SIZES[aspect_ratio(size)], "num_images": 1},
            timeout=120,
        )
        r.raise_for_status()
        images = r.json().get("images") or []
        if not images:
            raise RuntimeError("fal.ai rasm qaytarmadi")
        img = await self._http.get(images[0]["url"], timeout=60)
        img.raise_for_status()
        return img.content
