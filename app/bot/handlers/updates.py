"""Telegram update'lari: so'rovnoma natijalari, reaksiyalar, obunachilar harakati, bot huquqlari."""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.types import ChatMemberUpdated, MessageReactionCountUpdated, Poll

from app.context import AppContext


def _status(value: Any) -> str:
    return str(getattr(value, "value", value))


def _reaction_key(reaction_type: Any) -> str:
    emoji = getattr(reaction_type, "emoji", None)
    if emoji:
        return str(emoji)
    custom = getattr(reaction_type, "custom_emoji_id", None)
    if custom:
        return f"custom:{custom}"
    return str(getattr(reaction_type, "type", "other"))


async def on_poll(poll: Poll, ctx: AppContext) -> None:
    polls = ctx.services.get("polls")
    if polls is not None:
        await polls.on_poll_update(
            poll.id, [(o.text, o.voter_count) for o in poll.options], poll.total_voter_count, poll.is_closed
        )


async def on_reaction_count(event: MessageReactionCountUpdated, ctx: AppContext) -> None:
    metrics = ctx.services.get("metrics")
    if metrics is not None:
        await metrics.on_reaction_count(
            event.chat.id, event.message_id, [(_reaction_key(r.type), r.total_count) for r in event.reactions]
        )


async def on_chat_member(event: ChatMemberUpdated, ctx: AppContext) -> None:
    invites = ctx.services.get("invites")
    if invites is not None:
        await invites.on_member_update(
            event.chat.id,
            event.new_chat_member.user.id,
            _status(event.old_chat_member.status),
            _status(event.new_chat_member.status),
            event.invite_link.invite_link if event.invite_link else None,
        )


async def on_my_chat_member(event: ChatMemberUpdated, ctx: AppContext) -> None:
    old, new = _status(event.old_chat_member.status), _status(event.new_chat_member.status)
    title = event.chat.title or event.chat.username or event.chat.id
    await ctx.notifier.notify(
        f"ℹ️ Botning «{title}» ({event.chat.id}) dagi holati oʻzgardi: {old} → {new}",
        key=f"mychat:{event.chat.id}:{new}",
    )


def create_router() -> Router:
    router = Router(name="updates")
    router.poll.register(on_poll)
    router.message_reaction_count.register(on_reaction_count)
    router.chat_member.register(on_chat_member)
    router.my_chat_member.register(on_my_chat_member)
    return router
