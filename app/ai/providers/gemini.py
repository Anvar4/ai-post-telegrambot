"""Google Gemini (google-genai) mijozi."""

from __future__ import annotations

from typing import Any

from app.ai.types import Message, RawCompletion


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, *, http_client: Any = None, timeout: float = 120.0) -> None:
        from google import genai
        from google.genai import types

        self.model = model
        opts: dict[str, Any] = {"timeout": int(timeout * 1000)}
        if http_client is not None:
            opts["httpx_async_client"] = http_client
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(**opts))

    async def complete(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 1500,
    ) -> RawCompletion:
        from google.genai import types

        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        contents = []
        for m in messages:
            if m.role == "system":
                continue
            parts = [types.Part.from_text(text=m.content)]
            parts += [types.Part.from_bytes(data=img, mime_type="image/png") for img in m.images]
            contents.append(types.Content(role="model" if m.role == "assistant" else "user", parts=parts))
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
        )
        resp = await self._client.aio.models.generate_content(
            model=self.model, contents=contents, config=config
        )
        um = resp.usage_metadata
        return RawCompletion(
            text=resp.text or "",
            input_tokens=(um.prompt_token_count or 0) if um else 0,
            output_tokens=((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0,
            cached_tokens=(um.cached_content_token_count or 0) if um else 0,
        )

    async def list_models(self) -> list[str] | None:
        pager = await self._client.aio.models.list()
        return [(m.name or "").removeprefix("models/") async for m in pager]
