from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message

from app.bot.sender import AiogramSender


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(round(s, 3))
        self.t += s


class FakeBot:
    def __init__(self, retry_after: list[int] | None = None) -> None:
        self.retry_after = list(retry_after or [])
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        if self.retry_after:
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=1, text="x"),
                message="Too Many Requests",
                retry_after=self.retry_after.pop(0),
            )
        return Message(
            message_id=len(self.calls),
            date=datetime.now(UTC),
            chat=Chat(id=kwargs["chat_id"], type="channel"),
            text=kwargs["text"],
        )


async def test_sender_respects_retry_after() -> None:
    clock = Clock()
    bot = FakeBot(retry_after=[2])
    sender = AiogramSender(bot, clock=clock.now, sleep=clock.sleep)  # type: ignore[arg-type]
    mid = await sender.send_message(-100, "salom")
    assert mid == 2
    assert 2 in clock.sleeps
    assert bot.calls[-1]["parse_mode"] == "HTML"


async def test_sender_gives_up_after_three_retry_after() -> None:
    clock = Clock()
    bot = FakeBot(retry_after=[1, 1, 1, 1])
    sender = AiogramSender(bot, clock=clock.now, sleep=clock.sleep)  # type: ignore[arg-type]
    with pytest.raises(TelegramRetryAfter):
        await sender.send_message(-100, "salom")
    assert len(bot.calls) == 3


async def test_sender_one_per_second_per_chat() -> None:
    clock = Clock()
    bot = FakeBot()
    sender = AiogramSender(bot, clock=clock.now, sleep=clock.sleep)  # type: ignore[arg-type]
    await sender.send_message(-100, "a")
    await sender.send_message(-100, "b")
    assert clock.sleeps == [1.0]


async def test_sender_different_chats_do_not_wait() -> None:
    clock = Clock()
    bot = FakeBot()
    sender = AiogramSender(bot, clock=clock.now, sleep=clock.sleep)  # type: ignore[arg-type]
    await sender.send_message(-100, "a")
    await sender.send_message(-200, "b")
    assert clock.sleeps == []


async def test_sender_disables_link_preview_by_default() -> None:
    bot = FakeBot()
    clock = Clock()
    sender = AiogramSender(bot, clock=clock.now, sleep=clock.sleep)  # type: ignore[arg-type]
    await sender.send_message(-100, "a")
    assert bot.calls[0]["link_preview_options"].is_disabled is True


class FakeMediaBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _msg(self, name: str, kwargs: dict[str, Any]) -> Message:
        self.calls.append((name, kwargs))
        return Message(message_id=len(self.calls), date=datetime.now(UTC), chat=Chat(id=1, type="channel"))

    async def send_photo(self, **kwargs: Any) -> Message:
        return self._msg("photo", kwargs)

    async def send_video(self, **kwargs: Any) -> Message:
        return self._msg("video", kwargs)

    async def send_animation(self, **kwargs: Any) -> Message:
        return self._msg("animation", kwargs)


async def test_send_media_uses_file_id_by_type() -> None:
    clock = Clock()
    bot = FakeMediaBot()
    sender = AiogramSender(bot, clock=clock.now, sleep=clock.sleep)  # type: ignore[arg-type]
    await sender.send_media(-100, "photo", "AgP", "<b>a</b>")
    await sender.send_media(-100, "video", "BAV", None)
    await sender.send_media(-100, "animation", "CgA", "gif")
    assert [
        (n, k.get("photo") or k.get("video") or k.get("animation"), k["caption"]) for n, k in bot.calls
    ] == [
        ("photo", "AgP", "<b>a</b>"),
        ("video", "BAV", None),
        ("animation", "CgA", "gif"),
    ]
    assert all(k["parse_mode"] == "HTML" for _, k in bot.calls)
    with pytest.raises(ValueError):
        await sender.send_media(-100, "sticker", "x", None)
