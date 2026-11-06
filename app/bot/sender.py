"""Telegram'ga yagona chiqish yo'li: chatga ≤1 xabar/sek, 429 da `retry_after` kutiladi."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Protocol, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    ChatPermissions,
    InputPollOption,
    LinkPreviewOptions,
    ReplyParameters,
)

T = TypeVar("T")
MEDIA_TYPES = ("photo", "video", "animation")


class TelegramSender(Protocol):
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: Any = None,
        reply_to: int | None = None,
        direct_topic_id: int | None = None,
    ) -> int: ...

    async def send_photo(
        self, chat_id: int, photo: bytes, caption: str | None = None, *, reply_markup: Any = None
    ) -> int: ...

    async def send_media(
        self,
        chat_id: int,
        media_type: str,
        file_id: str,
        caption: str | None = None,
        *,
        reply_markup: Any = None,
    ) -> int: ...

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
    ) -> tuple[int, str]: ...

    async def stop_poll(self, chat_id: int, message_id: int) -> dict[str, Any]: ...

    async def edit_reply_markup(self, chat_id: int, message_id: int, reply_markup: Any) -> None: ...

    async def member_count(self, chat_id: int) -> int: ...

    async def delete_message(self, chat_id: int, message_id: int) -> None: ...

    async def restrict(self, chat_id: int, user_id: int, until: datetime) -> None: ...

    async def ban(self, chat_id: int, user_id: int) -> None: ...

    async def create_invite_link(self, chat_id: int, name: str) -> str: ...

    async def send_document(
        self, chat_id: int, data: bytes, filename: str, caption: str | None = None
    ) -> int: ...


class AiogramSender:
    def __init__(
        self,
        bot: Bot,
        *,
        min_interval: float = 1.0,
        max_retries: int = 3,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.bot = bot
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._clock = clock
        self._sleep = sleep
        self._last: dict[int, float] = {}
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _throttle(self, chat_id: int) -> None:
        last = self._last.get(chat_id)
        if last is not None:
            wait = self.min_interval - (self._clock() - last)
            if wait > 0:
                await self._sleep(wait)

    async def _send(self, chat_id: int, call: Callable[[], Awaitable[T]]) -> T:
        async with self._locks[chat_id]:
            for attempt in range(1, self.max_retries + 1):
                await self._throttle(chat_id)
                try:
                    result = await call()
                except TelegramRetryAfter as exc:
                    self._last[chat_id] = self._clock()
                    if attempt == self.max_retries:
                        raise
                    await self._sleep(float(exc.retry_after))
                    continue
                self._last[chat_id] = self._clock()
                return result
        raise RuntimeError("unreachable")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: Any = None,
        reply_to: int | None = None,
        direct_topic_id: int | None = None,
    ) -> int:
        msg = await self._send(
            chat_id,
            lambda: self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                reply_parameters=ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
                if reply_to
                else None,
                direct_messages_topic_id=direct_topic_id,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
        )
        return msg.message_id

    async def send_photo(
        self, chat_id: int, photo: bytes, caption: str | None = None, *, reply_markup: Any = None
    ) -> int:
        msg = await self._send(
            chat_id,
            lambda: self.bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(photo, filename="cover.png"),
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            ),
        )
        return msg.message_id

    async def send_media(
        self,
        chat_id: int,
        media_type: str,
        file_id: str,
        caption: str | None = None,
        *,
        reply_markup: Any = None,
    ) -> int:
        """Telegram'dagi fayl (file_id) bilan rasm / video / animatsiya yuborish."""
        if media_type not in MEDIA_TYPES:
            raise ValueError(f"media turi qoʻllab-quvvatlanmaydi: {media_type}")
        method = getattr(self.bot, f"send_{media_type}")
        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            media_type: file_id,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        }
        msg = await self._send(chat_id, lambda: method(**kwargs))
        return int(msg.message_id)

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
        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "question": question,
            "options": [InputPollOption(text=o) for o in options],
            "is_anonymous": is_anonymous,
            "type": "quiz" if quiz else "regular",
        }
        if quiz and correct_option_id is not None:
            kwargs["correct_option_ids"] = [correct_option_id]
            if explanation:
                kwargs["explanation"] = explanation
        msg = await self._send(chat_id, lambda: self.bot.send_poll(**kwargs))
        return msg.message_id, msg.poll.id if msg.poll else ""

    async def stop_poll(self, chat_id: int, message_id: int) -> dict[str, Any]:
        poll = await self._send(chat_id, lambda: self.bot.stop_poll(chat_id=chat_id, message_id=message_id))
        return {
            "options": [{"text": o.text, "voter_count": o.voter_count} for o in poll.options],
            "total_voter_count": poll.total_voter_count,
        }

    async def edit_reply_markup(self, chat_id: int, message_id: int, reply_markup: Any) -> None:
        await self._send(
            chat_id,
            lambda: self.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            ),
        )

    async def member_count(self, chat_id: int) -> int:
        return await self.bot.get_chat_member_count(chat_id=chat_id)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        await self.bot.delete_message(chat_id=chat_id, message_id=message_id)

    async def restrict(self, chat_id: int, user_id: int, until: datetime) -> None:
        await self.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )

    async def ban(self, chat_id: int, user_id: int) -> None:
        await self.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)

    async def create_invite_link(self, chat_id: int, name: str) -> str:
        link = await self.bot.create_chat_invite_link(chat_id=chat_id, name=name[:32])
        return link.invite_link

    async def send_document(
        self, chat_id: int, data: bytes, filename: str, caption: str | None = None
    ) -> int:
        msg = await self._send(
            chat_id,
            lambda: self.bot.send_document(
                chat_id=chat_id,
                document=BufferedInputFile(data, filename=filename),
                caption=caption,
                parse_mode="HTML",
            ),
        )
        return msg.message_id
