"""Sozlamalardan AI mijozlarini yig'ish."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.ai.types import ImageClient, LLMClient
from app.config import IMAGE_PROVIDERS, MAIN_PROVIDERS, Settings

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


@dataclass
class Clients:
    writer: LLMClient | None = None
    editor: LLMClient | None = None
    fast: LLMClient | None = None
    image: ImageClient | None = None
    problems: list[str] = field(default_factory=list)

    def as_roles(self) -> dict[str, LLMClient | None]:
        return {"writer": self.writer, "editor": self.editor, "fast": self.fast}


def _secret(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else str(value)


def _build_writer(s: Settings, problems: list[str]) -> LLMClient | None:
    provider = s.llm_main_provider
    if provider is None:
        problems.append("LLM_MAIN_PROVIDER sozlanmagan — yozuvchi vazifasini gpt-6-sol bajaradi")
        return None
    if provider not in MAIN_PROVIDERS:
        problems.append(f"LLM_MAIN_PROVIDER='{provider}' noma'lum. Mumkin: {' | '.join(MAIN_PROVIDERS)}")
        return None
    if not s.llm_main_model:
        hint = (
            " (DeepSeek uchun masalan: deepseek-v4-pro yoki deepseek-flash)" if provider == "deepseek" else ""
        )
        problems.append(f"LLM_MAIN_MODEL bo'sh — yozuvchi o'chirilgan, zaxira ishlaydi{hint}")
        return None
    key = _secret(s.llm_main_api_key) or (_secret(s.openai_api_key) if provider == "openai" else None)
    if not key:
        problems.append("LLM_MAIN_API_KEY bo'sh — yozuvchi o'chirilgan, zaxira ishlaydi")
        return None
    timeout = s.ai_timeout
    if provider == "anthropic":
        from app.ai.providers.anthropic import AnthropicClient

        return AnthropicClient(key, s.llm_main_model, timeout=timeout)
    if provider == "gemini":
        from app.ai.providers.gemini import GeminiClient

        return GeminiClient(key, s.llm_main_model, timeout=timeout)
    if provider == "deepseek":
        from app.ai.providers.openai_compat import OpenAICompatClient

        client = OpenAICompatClient(
            key, s.llm_main_model, base_url=s.llm_main_base_url or DEEPSEEK_BASE_URL, timeout=timeout
        )
        client.provider = "deepseek"
        return client
    if provider == "openai_compatible":
        if not s.llm_main_base_url:
            problems.append("openai_compatible uchun LLM_MAIN_BASE_URL kerak — yozuvchi o'chirilgan")
            return None
        from app.ai.providers.openai_compat import OpenAICompatClient

        return OpenAICompatClient(key, s.llm_main_model, base_url=s.llm_main_base_url, timeout=timeout)
    from app.ai.providers.openai import OpenAIClient

    return OpenAIClient(key, s.llm_main_model, timeout=timeout)


def _build_image(s: Settings, http: httpx.AsyncClient | None, problems: list[str]) -> ImageClient | None:
    provider = s.image_provider
    if provider is None and s.image_api_key is not None:
        problems.append(
            f"IMAGE_API_KEY bor, lekin IMAGE_PROVIDER koʻrsatilmagan ({' | '.join(IMAGE_PROVIDERS[:-1])})"
        )
        return None
    if provider in (None, "none"):
        return None
    if provider not in IMAGE_PROVIDERS:
        problems.append(f"IMAGE_PROVIDER='{provider}' noma'lum. Mumkin: {' | '.join(IMAGE_PROVIDERS)}")
        return None
    key = _secret(s.image_api_key) or (_secret(s.openai_api_key) if provider == "openai" else None)
    if not key:
        problems.append("IMAGE_API_KEY bo'sh — rasmlar brend shablonidan chiziladi")
        return None
    if provider == "openai":
        from app.ai.images.openai_img import OpenAIImageClient

        return OpenAIImageClient(key, s.image_model or "gpt-image-2")
    if provider == "gemini":
        from app.ai.images.gemini_img import GeminiImageClient

        return GeminiImageClient(key, s.image_model or "imagen-4.0-generate-001")
    client = http or httpx.AsyncClient(timeout=120)
    if provider == "stability":
        from app.ai.images.stability_img import StabilityImageClient

        return StabilityImageClient(key, s.image_model, http=client)
    if provider == "replicate":
        from app.ai.images.replicate_img import ReplicateImageClient

        return ReplicateImageClient(key, s.image_model, http=client)
    from app.ai.images.fal_img import FalImageClient

    return FalImageClient(key, s.image_model, http=client)


def build_clients(s: Settings, http: httpx.AsyncClient | None = None) -> Clients:
    problems: list[str] = []
    editor = fast = None
    openai_key = _secret(s.openai_api_key)
    if openai_key:
        from app.ai.providers.openai import OpenAIClient

        editor = OpenAIClient(openai_key, s.openai_editor_model, timeout=s.ai_timeout)
        fast = OpenAIClient(openai_key, s.openai_fast_model, timeout=s.ai_timeout)
    else:
        problems.append(
            "OPENAI_API_KEY bo'sh — muharrir va filtr vazifalarini yozuvchi bajaradi (sifat pasayadi)"
        )
    writer = _build_writer(s, problems)
    image = _build_image(s, http, problems)
    return Clients(writer=writer, editor=editor, fast=fast, image=image, problems=problems)
