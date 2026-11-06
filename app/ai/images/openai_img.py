"""OpenAI rasm generatsiyasi (gpt-image-*)."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.ai.types import aspect_ratio

_SIZES = {"1:1": "1024x1024", "16:9": "1536x1024", "9:16": "1024x1536"}


class OpenAIImageClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str, *, http_client: Any = None, timeout: float = 180.0) -> None:
        from openai import AsyncOpenAI

        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, http_client=http_client, max_retries=0, timeout=timeout)

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        resp = await self._client.images.generate(
            model=self.model, prompt=prompt, size=_SIZES[aspect_ratio(size)], n=1
        )
        item = resp.data[0] if resp.data else None
        if item is None:
            raise RuntimeError("OpenAI rasm qaytarmadi")
        if item.b64_json:
            return base64.b64decode(item.b64_json)
        if item.url:
            async with httpx.AsyncClient(timeout=60) as http:
                r = await http.get(item.url)
                r.raise_for_status()
                return r.content
        raise RuntimeError("OpenAI javobida rasm yo'q")
