"""Stability AI (Stable Image) REST mijozi."""

from __future__ import annotations

import httpx

from app.ai.types import aspect_ratio


class StabilityImageClient:
    provider = "stability"

    def __init__(self, api_key: str, model: str | None, *, http: httpx.AsyncClient) -> None:
        self.model = model or "core"
        self._key = api_key
        self._http = http

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        endpoint = self.model if self.model in {"core", "ultra", "sd3"} else "core"
        r = await self._http.post(
            f"https://api.stability.ai/v2beta/stable-image/generate/{endpoint}",
            headers={"Authorization": f"Bearer {self._key}", "Accept": "image/*"},
            files={"none": ("", b"")},
            data={"prompt": prompt, "aspect_ratio": aspect_ratio(size), "output_format": "png"},
            timeout=120,
        )
        r.raise_for_status()
        return r.content
