"""Testlar uchun soxta AI mijozlari, notifier va Telegram sender."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.ai.types import Message, RawCompletion


class ScriptedLLM:
    """Navbat bilan javob qaytaradi: str — matn, Exception — xato, callable — messages dan javob."""

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-6-sol",
        script: list[Any] | None = None,
        *,
        tokens: tuple[int, int] = (100, 50),
        delay: float = 0.0,
        models: list[str] | None = None,
    ):
        self.provider = provider
        self.model = model
        self.script = list(script or [])
        self.tokens = tokens
        self.delay = delay
        self.calls: list[list[Message]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.models = models

    async def complete(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 1500,
    ) -> RawCompletion:
        self.calls.append(list(messages))
        self.kwargs.append({"json_mode": json_mode, "temperature": temperature, "max_tokens": max_tokens})
        if self.delay:
            await asyncio.sleep(self.delay)
        if not self.script:
            raise AssertionError(f"{self.model}: kutilmagan chaqiruv")
        item = self.script.pop(0)
        if callable(item) and not isinstance(item, Exception):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, RawCompletion):
            return item
        return RawCompletion(text=str(item), input_tokens=self.tokens[0], output_tokens=self.tokens[1])

    async def list_models(self) -> list[str] | None:
        return self.models


class RoutedLLM:
    """Promptdagi kalit so'zga qarab javob beradi (pipeline testlari uchun)."""

    def __init__(self, provider: str, model: str, routes: list[tuple[str, Any]], default: Any = None):
        self.provider = provider
        self.model = model
        self.routes = routes
        self.default = default
        self.calls: list[list[Message]] = []

    async def complete(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 1500,
    ) -> RawCompletion:
        self.calls.append(list(messages))
        prompt = "\n".join(m.content for m in messages)
        for needle, answer in self.routes:
            if needle in prompt:
                value = answer(messages) if callable(answer) else answer
                if isinstance(value, Exception):
                    raise value
                return RawCompletion(text=value, input_tokens=100, output_tokens=50)
        if self.default is None:
            raise AssertionError(f"{self.model}: mos route yo'q: {prompt[:200]}")
        value = self.default(messages) if callable(self.default) else self.default
        return RawCompletion(text=value, input_tokens=100, output_tokens=50)

    async def list_models(self) -> list[str] | None:
        return None


class FakeImage:
    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-image-2",
        fail: bool = False,
        data: bytes | None = None,
    ):
        self.provider = provider
        self.model = model
        self.fail = fail
        self.data = data
        self.prompts: list[str] = []

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("image provider down")
        if self.data is not None:
            return self.data
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (1024, 1024), (11, 31, 58)).save(buf, format="PNG")
        return buf.getvalue()


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None]] = []

    async def notify(self, text: str, *, key: str | None = None) -> None:
        self.messages.append((text, key))


@dataclass
class Sent:
    method: str
    chat_id: int
    text: str | None = None
    photo: bytes | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    message_id: int = 0


class FakeSender:
    def __init__(self, *, fail_times: int = 0, member_count: int = 1000) -> None:
        self.sent: list[Sent] = []
        self._ids = itertools.count(100)
        self.fail_times = fail_times
        self.deleted: list[tuple[int, int]] = []
        self.restricted: list[tuple[int, int]] = []
        self.banned: list[tuple[int, int]] = []
        self.stopped: list[tuple[int, int]] = []
        self.members = member_count
        self.invite_links: list[str] = []
        self.on_send: Callable[[Sent], None] | None = None

    def _maybe_fail(self) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("telegram down")

    def _record(self, sent: Sent) -> int:
        self._maybe_fail()
        sent.message_id = next(self._ids)
        self.sent.append(sent)
        if self.on_send:
            self.on_send(sent)
        return sent.message_id

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: Any = None,
        reply_to: int | None = None,
        direct_topic_id: int | None = None,
    ) -> int:
        return self._record(
            Sent(
                "message",
                chat_id,
                text=text,
                kwargs={
                    "reply_markup": reply_markup,
                    "reply_to": reply_to,
                    "direct_topic_id": direct_topic_id,
                },
            )
        )

    async def send_photo(
        self, chat_id: int, photo: bytes, caption: str | None = None, *, reply_markup: Any = None
    ) -> int:
        return self._record(
            Sent("photo", chat_id, text=caption, photo=photo, kwargs={"reply_markup": reply_markup})
        )

    async def send_media(
        self,
        chat_id: int,
        media_type: str,
        file_id: str,
        caption: str | None = None,
        *,
        reply_markup: Any = None,
    ) -> int:
        return self._record(
            Sent(
                "media",
                chat_id,
                text=caption,
                kwargs={"media_type": media_type, "file_id": file_id, "reply_markup": reply_markup},
            )
        )

    async def send_poll(
        self,
        chat_id: int,
        *,
        question: str,
        options: list[str],
        quiz: bool = False,
        correct_option_id: int | None = None,
        explanation: str | None = None,
        is_anonymous: bool = True,
    ) -> tuple[int, str]:
        mid = self._record(
            Sent(
                "poll",
                chat_id,
                text=question,
                kwargs={
                    "options": options,
                    "quiz": quiz,
                    "correct_option_id": correct_option_id,
                    "explanation": explanation,
                    "is_anonymous": is_anonymous,
                },
            )
        )
        return mid, f"poll-{mid}"

    async def stop_poll(self, chat_id: int, message_id: int) -> dict[str, Any]:
        self.stopped.append((chat_id, message_id))
        return {"options": [], "total_voter_count": 0}

    async def member_count(self, chat_id: int) -> int:
        return self.members

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))

    async def restrict(self, chat_id: int, user_id: int, until: Any) -> None:
        self.restricted.append((chat_id, user_id))

    async def ban(self, chat_id: int, user_id: int) -> None:
        self.banned.append((chat_id, user_id))

    async def create_invite_link(self, chat_id: int, name: str) -> str:
        url = f"https://t.me/+fake{len(self.invite_links)}"
        self.invite_links.append(url)
        return url

    async def send_document(
        self, chat_id: int, data: bytes, filename: str, caption: str | None = None
    ) -> int:
        return self._record(Sent("document", chat_id, text=caption, kwargs={"filename": filename}))
