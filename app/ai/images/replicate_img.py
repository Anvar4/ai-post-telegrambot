"""Replicate REST mijozi (`Prefer: wait` bilan sinxron natija)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.ai.types import aspect_ratio


class ReplicateImageClient:
    provider = "replicate"

    def __init__(self, api_key: str, model: str | None, *, http: httpx.AsyncClient) -> None:
        self.model = model or "black-forest-labs/flux-schnell"
        self._key = api_key
        self._http = http

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        headers = {"Authorization": f"Bearer {self._key}", "Prefer": "wait"}
        r = await self._http.post(
            f"https://api.replicate.com/v1/models/{self.model}/predictions",
            headers=headers,
            json={"input": {"prompt": prompt, "aspect_ratio": aspect_ratio(size), "output_format": "png"}},
            timeout=120,
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        for _ in range(30):
            if data.get("status") in {"succeeded", "failed", "canceled"}:
                break
            await asyncio.sleep(2)
            poll = await self._http.get(data["urls"]["get"], headers=headers, timeout=30)
            poll.raise_for_status()
            data = poll.json()
        if data.get("status") != "succeeded":
            raise RuntimeError(f"Replicate: {data.get('status')} {data.get('error')}")
        output = data.get("output")
        url = output[0] if isinstance(output, list) else output
        img = await self._http.get(str(url), timeout=60)
        img.raise_for_status()
        return img.content
