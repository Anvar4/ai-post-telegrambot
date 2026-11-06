"""MongoDB ulanishi va indekslar."""

from __future__ import annotations

from typing import Any

ASC, DESC = 1, -1

INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict[str, Any]]]] = {
    "sources": [([("url", ASC)], {"unique": True})],
    "articles": [
        ([("url_hash", ASC)], {"unique": True}),
        ([("story_id", ASC)], {}),
        ([("fetched_at", DESC)], {}),
    ],
    "stories": [([("status", ASC), ("first_seen", DESC)], {}), ([("first_seen", DESC)], {})],
    "posts": [
        ([("status", ASC), ("scheduled_at", ASC)], {}),
        ([("chat_id", ASC), ("message_id", ASC)], {}),
        ([("discussion_message_id", ASC)], {}),
        ([("slot", ASC)], {}),
        ([("created_at", DESC)], {}),
        ([("published_at", DESC)], {}),
    ],
    "polls": [([("telegram_poll_id", ASC)], {}), ([("post_id", ASC)], {})],
    "post_metrics": [([("post_id", ASC), ("_id", DESC)], {})],
    "subscriber_snapshots": [([("ts", DESC)], {})],
    "invite_links": [([("url", ASC)], {"unique": True})],
    "member_events": [([("user_hash", ASC), ("_id", DESC)], {}), ([("ts", DESC)], {})],
    "qa_logs": [([("ts", DESC)], {}), ([("user_hash", ASC)], {})],
    "moderation_events": [([("user_hash", ASC), ("chat_id", ASC), ("ts", DESC)], {}), ([("ts", DESC)], {})],
    "llm_usage": [([("ts", DESC)], {})],
    "audit_log": [([("action", ASC), ("ts", DESC)], {})],
}


def connect(uri: str, db_name: str) -> tuple[Any, Any]:
    """AsyncMongoClient va bot bazasi (`tz_aware=True` — vaqtlar UTC aware qaytadi)."""
    from pymongo import AsyncMongoClient

    client: Any = AsyncMongoClient(
        uri, tz_aware=True, serverSelectionTimeoutMS=20_000, appname="it-dunyosi-bot"
    )
    return client, client[db_name]


async def ensure_indexes(db: Any) -> None:
    for collection, specs in INDEXES.items():
        for keys, options in specs:
            await db[collection].create_index(keys, **options)
