"""OpenAI bilan mos API'lar (DeepSeek, OpenRouter va h.k.): `max_tokens` parametri bilan."""

from __future__ import annotations

from app.ai.providers.openai import OpenAIClient


class OpenAICompatClient(OpenAIClient):
    provider = "openai_compatible"
    _token_param = "max_tokens"

    async def list_models(self) -> list[str] | None:
        try:
            return await super().list_models()
        except Exception:
            return None  # ko'p mos API'larda /models yo'q
