"""Anthropic (Claude) Messages API mijozi."""

from __future__ import annotations

import base64
from typing import Any

from app.ai.types import Message, RawCompletion


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, *, http_client: Any = None, timeout: float = 120.0) -> None:
        from anthropic import AsyncAnthropic

        self.model = model
        self._client = AsyncAnthropic(
            api_key=api_key, http_client=http_client, max_retries=0, timeout=timeout
        )

    @staticmethod
    def _content(m: Message) -> Any:
        if not m.images:
            return m.content
        parts: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(img).decode(),
                },
            }
            for img in m.images
        ]
        parts.append({"type": "text", "text": m.content})
        return parts

    async def complete(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 1500,
    ) -> RawCompletion:
        # Joriy SDK temperature parametrini qabul qilmaydi; JSON — prompt orqali.
        system = [
            {
                "type": "text",
                "text": m.content,
                **({"cache_control": {"type": "ephemeral"}} if m.cache else {}),
            }
            for m in messages
            if m.role == "system"
        ]
        chat = [{"role": m.role, "content": self._content(m)} for m in messages if m.role != "system"]
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": chat}
        if system:
            kwargs["system"] = system
        resp = await self._client.messages.create(**kwargs)
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        return RawCompletion(
            text=text,
            input_tokens=(u.input_tokens or 0) + cache_read + cache_write,
            output_tokens=u.output_tokens or 0,
            cached_tokens=cache_read,
            truncated=getattr(resp, "stop_reason", None) == "max_tokens",
        )

    async def list_models(self) -> list[str] | None:
        return [m.id async for m in self._client.models.list()]
