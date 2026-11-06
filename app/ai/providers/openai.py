"""OpenAI Chat Completions mijozi (muharrir, tez filtr va ixtiyoriy yozuvchi)."""

from __future__ import annotations

import base64
from typing import Any

from app.ai.types import Message, RawCompletion


class OpenAIClient:
    provider = "openai"
    _token_param = "max_completion_tokens"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        http_client: Any = None,
        timeout: float = 120.0,
    ) -> None:
        from openai import AsyncOpenAI

        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            http_client=http_client,
            max_retries=0,
            timeout=timeout,
        )
        self._no_temperature = False

    @staticmethod
    def _message(m: Message) -> dict[str, Any]:
        if not m.images:
            return {"role": m.role, "content": m.content}
        parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
        for img in m.images:
            b64 = base64.b64encode(img).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        return {"role": m.role, "content": parts}

    async def complete(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 1500,
    ) -> RawCompletion:
        from openai import BadRequestError

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(m) for m in messages],
            self._token_param: max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if not self._no_temperature:
            payload["temperature"] = temperature
        try:
            resp = await self._client.chat.completions.create(**payload)
        except BadRequestError as exc:
            if "temperature" in payload and "temperature" in str(exc).lower():
                # Reasoning modellar temperature qabul qilmaydi — eslab qolamiz
                self._no_temperature = True
                payload.pop("temperature")
                resp = await self._client.chat.completions.create(**payload)
            else:
                raise
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        truncated = bool(resp.choices) and resp.choices[0].finish_reason == "length"
        usage = resp.usage
        cached = 0
        if usage is not None and usage.prompt_tokens_details is not None:
            cached = usage.prompt_tokens_details.cached_tokens or 0
        return RawCompletion(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=cached,
            truncated=truncated,
        )

    async def list_models(self) -> list[str] | None:
        return [m.id async for m in self._client.models.list()]
