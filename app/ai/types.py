"""AI qatlamining umumiy turlari va protokollari."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["writer", "editor", "fast"]


@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
    images: list[bytes] = field(default_factory=list)
    cache: bool = False  # statik qism: prompt caching uchun belgi


@dataclass
class RawCompletion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMResult:
    text: str
    parsed: Any
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    model: str
    provider: str
    role: str
    fallback_used: bool = False
    cost_usd: float = 0.0


class LLMClient(Protocol):
    provider: str
    model: str

    async def complete(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 1500,
    ) -> RawCompletion: ...

    async def list_models(self) -> list[str] | None: ...


class ImageClient(Protocol):
    provider: str
    model: str

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes: ...


class AIError(Exception):
    pass


class SchemaError(AIError):
    """Javob JSON sxemaga mos kelmadi (qayta so'rovdan keyin ham)."""


class BudgetExceededError(AIError):
    """Kunlik budjet tugadi; ixtiyoriy vazifalar to'xtatildi."""


class NoProviderError(AIError):
    """Rol uchun provayder sozlanmagan."""


def aspect_ratio(size: str) -> str:
    """'1536x1024' -> '16:9', '1024x1024' -> '1:1'."""
    try:
        w, h = (int(x) for x in size.lower().split("x"))
    except ValueError:
        return "1:1"
    ratio = w / h if h else 1
    if ratio >= 1.4:
        return "16:9"
    if ratio <= 0.72:
        return "9:16"
    return "1:1"
