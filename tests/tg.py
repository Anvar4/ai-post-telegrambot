"""aiogram handlerlarini haqiqiy Dispatcher orqali sinash uchun yordamchilar."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage, SendPhoto, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, Update, User


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self._mid = 1000

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.requests.append(method)
        returning = getattr(method, "__returning__", None)
        if returning is Message:
            self._mid += 1
            chat_id = int(getattr(method, "chat_id", 0) or 0)
            return Message(
                message_id=self._mid,
                date=datetime.now(UTC),
                chat=Chat(id=chat_id, type="private"),
                text=getattr(method, "text", None) or getattr(method, "caption", None),
            )
        if returning is bool:
            return True
        return None

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def close(self) -> None:
        return None


def make_bot() -> Bot:
    return Bot(token="42:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123", session=RecordingSession())


_uid = iter(range(1, 10_000_000))


def msg_update(
    text: str, user_id: int, *, chat_id: int | None = None, chat_type: str = "private", **extra: Any
) -> Update:
    n = next(_uid)
    chat = Chat(id=chat_id if chat_id is not None else user_id, type=chat_type)
    user = User(id=user_id, is_bot=False, first_name="Test")
    return Update(
        update_id=n,
        message=Message(message_id=n, date=datetime.now(UTC), chat=chat, from_user=user, text=text, **extra),
    )


def media_update(user_id: int, *, chat_type: str = "private", **media: Any) -> Update:
    """Rasm/video/animatsiya xabari (matnsiz; caption va caption_entities ixtiyoriy)."""
    n = next(_uid)
    chat = Chat(id=user_id, type=chat_type)
    user = User(id=user_id, is_bot=False, first_name="Test")
    return Update(
        update_id=n,
        message=Message(message_id=n, date=datetime.now(UTC), chat=chat, from_user=user, **media),
    )


def callback_update(data: str, user_id: int, *, chat_id: int | None = None) -> Update:
    n = next(_uid)
    chat = Chat(id=chat_id if chat_id is not None else user_id, type="private")
    user = User(id=user_id, is_bot=False, first_name="Test")
    msg = Message(message_id=n, date=datetime.now(UTC), chat=chat, from_user=user, text="...")
    return Update(
        update_id=n,
        callback_query=CallbackQuery(id=str(n), from_user=user, chat_instance="ci", message=msg, data=data),
    )


def sent_texts(bot: Bot) -> list[str]:
    session: RecordingSession = bot.session  # type: ignore[assignment]
    out = []
    for m in session.requests:
        if isinstance(m, SendMessage):
            out.append(m.text)
        elif isinstance(m, SendPhoto):
            out.append(m.caption or "")
    return out


def callback_answers(bot: Bot) -> list[str]:
    session: RecordingSession = bot.session  # type: ignore[assignment]
    return [m.text or "" for m in session.requests if isinstance(m, AnswerCallbackQuery)]


def last_markup(bot: Bot) -> InlineKeyboardMarkup | None:
    """Bot yuborgan oxirgi inline klaviatura (handler javoblari orasidan)."""
    session: RecordingSession = bot.session  # type: ignore[assignment]
    for m in reversed(session.requests):
        markup = getattr(m, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            return markup
    return None


def button_data(markup: Any) -> dict[str, str]:
    """Tugma matni -> callback_data."""
    assert markup is not None, "klaviatura yoʻq"
    return {b.text: b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data}
