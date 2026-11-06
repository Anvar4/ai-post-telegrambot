"""MongoDB maʼlumot qatlami: umumiy `Collection[T]` va `Repo` (sozlamalar, audit, xarajat, tozalash)."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Generic, TypeVar

from pymongo import ReturnDocument
from pymongo.errors import BulkWriteError

from app.db.models import (
    Article,
    AuditLog,
    Doc,
    InviteLink,
    LLMUsage,
    MemberEvent,
    ModerationEvent,
    Poll,
    Post,
    PostMetric,
    QALog,
    Source,
    Story,
    SubscriberSnapshot,
)
from app.utils.timeutil import day_bounds, utcnow

T = TypeVar("T", bound=Doc)
Sort = list[tuple[str, int]]


def encode(value: Any) -> Any:
    """Python → BSON: aware datetime → naive UTC (pymongo va mongomock da bir xil), Enum → qiymati."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [encode(v) for v in value]
    return value


def decode(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, dict):
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def to_doc(obj: Doc) -> dict[str, Any]:
    doc = {f.name: encode(getattr(obj, f.name)) for f in dataclasses.fields(obj) if f.name != "id"}
    doc["_id"] = obj.id
    return doc


def from_doc(model: type[T], doc: dict[str, Any]) -> T:
    names = {f.name for f in dataclasses.fields(model)}
    kwargs = {k: decode(v) for k, v in doc.items() if k in names}
    kwargs["id"] = doc.get("_id")
    return model(**kwargs)


class Collection(Generic[T]):
    def __init__(self, repo: Repo, model: type[T]) -> None:
        self.repo = repo
        self.model = model
        self.name = model.__collection__
        self.raw = repo.db[self.name]

    async def insert(self, obj: T) -> T:
        if obj.id is None:
            obj.id = await self.repo.next_id(self.name)
        await self.raw.insert_one(to_doc(obj))
        return obj

    async def insert_many(self, objs: list[T]) -> int:
        """Ko'p hujjatni bitta so'rovda qo'shadi; takroriy (unique) hujjatlar o'tkazib yuboriladi."""
        if not objs:
            return 0
        missing = [o for o in objs if o.id is None]
        for obj, new_id in zip(missing, await self.repo.next_ids(self.name, len(missing)), strict=True):
            obj.id = new_id
        try:
            res = await self.raw.insert_many([to_doc(o) for o in objs], ordered=False)
            return len(res.inserted_ids)
        except BulkWriteError as exc:
            return int(exc.details.get("nInserted", 0))

    async def get(self, obj_id: int | None) -> T | None:
        if obj_id is None:
            return None
        doc = await self.raw.find_one({"_id": obj_id})
        return from_doc(self.model, doc) if doc else None

    async def find(
        self, filter: dict[str, Any] | None = None, *, sort: Sort | None = None, limit: int = 0
    ) -> list[T]:
        cursor = self.raw.find(encode(filter or {}))
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return [from_doc(self.model, d) for d in await cursor.to_list(None)]

    async def find_one(self, filter: dict[str, Any], *, sort: Sort | None = None) -> T | None:
        rows = await self.find(filter, sort=sort, limit=1)
        return rows[0] if rows else None

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        return int(await self.raw.count_documents(encode(filter or {})))

    async def save(self, obj: T) -> None:
        if obj.id is None:
            await self.insert(obj)
            return
        await self.raw.replace_one({"_id": obj.id}, to_doc(obj), upsert=True)

    async def update(self, obj_id: int, fields: dict[str, Any]) -> None:
        await self.raw.update_one({"_id": obj_id}, {"$set": encode(fields)})

    async def cas(self, obj_id: int, expected: dict[str, Any], fields: dict[str, Any]) -> bool:
        """Atomik shartli yangilash: faqat `expected` mos kelsa oʻzgartiradi (ikki marta nashrdan himoya)."""
        res = await self.raw.update_one({"_id": obj_id, **encode(expected)}, {"$set": encode(fields)})
        return int(res.modified_count) == 1

    async def update_where(self, filter: dict[str, Any], update: dict[str, Any]) -> int:
        res = await self.raw.update_many(encode(filter), encode(update))
        return int(res.modified_count)

    async def delete_where(self, filter: dict[str, Any]) -> int:
        res = await self.raw.delete_many(encode(filter))
        return int(res.deleted_count)


class Repo:
    def __init__(self, db: Any, tz: str = "Asia/Tashkent") -> None:
        self.db = db
        self.tz = tz
        self.sources = Collection(self, Source)
        self.articles = Collection(self, Article)
        self.stories = Collection(self, Story)
        self.posts = Collection(self, Post)
        self.polls = Collection(self, Poll)
        self.post_metrics = Collection(self, PostMetric)
        self.snapshots = Collection(self, SubscriberSnapshot)
        self.invite_links = Collection(self, InviteLink)
        self.member_events = Collection(self, MemberEvent)
        self.qa_logs = Collection(self, QALog)
        self.moderation_events = Collection(self, ModerationEvent)
        self.llm_usage = Collection(self, LLMUsage)
        self.audit_log = Collection(self, AuditLog)

    def collection(self, model: type[T]) -> Collection[T]:
        for value in vars(self).values():
            if isinstance(value, Collection) and value.model is model:
                return value
        raise KeyError(model.__name__)

    async def add(self, *docs: Doc) -> None:
        """Bir nechta hujjatni (har xil turdagi) qo'shish — `id` lar beriladi."""
        for doc in docs:
            await self.collection(type(doc)).insert(doc)

    async def all(self, model: type[T]) -> list[T]:
        return await self.collection(model).find({}, sort=[("_id", 1)])

    async def get(self, model: type[T], obj_id: int | None) -> T | None:
        return await self.collection(model).get(obj_id)

    async def count(self, model: type[T], filter: dict[str, Any] | None = None) -> int:
        return await self.collection(model).count(filter)

    async def next_id(self, name: str) -> int:
        return (await self.next_ids(name, 1))[0]

    async def next_ids(self, name: str, n: int) -> list[int]:
        """`n` ta ketma-ket id ni bitta atomik so'rovda ajratadi."""
        if n <= 0:
            return []
        doc = await self.db["counters"].find_one_and_update(
            {"_id": name}, {"$inc": {"seq": n}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        last = int(doc["seq"])
        return list(range(last - n + 1, last + 1))

    # --- sozlamalar ---

    async def get_setting(self, key: str, default: Any = None) -> Any:
        doc = await self.db["settings"].find_one({"_id": key})
        return default if doc is None else decode(doc.get("value"))

    async def set_setting(self, key: str, value: Any) -> None:
        await self.db["settings"].replace_one({"_id": key}, {"_id": key, "value": encode(value)}, upsert=True)

    # --- audit va xatolar ---

    async def audit(self, actor: str, action: str, /, **details: Any) -> None:
        await self.audit_log.insert(
            AuditLog(ts=utcnow(), actor=actor, action=action, details=encode(details))
        )

    async def recent_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.audit_log.find({"action": "error"}, sort=[("_id", -1)], limit=limit)
        return [{"ts": r.ts, **r.details} for r in rows]

    async def count_errors(self, since: datetime) -> int:
        return await self.audit_log.count({"action": "error", "ts": {"$gte": since}})

    # --- AI xarajati ---

    async def record_usage(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: float = 0.0,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        await self.llm_usage.insert(
            LLMUsage(
                ts=utcnow(),
                role=role,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                cost_usd=cost_usd,
                ok=ok,
                error=error[:500] if error else None,
            )
        )

    async def spent_today(self, now: datetime | None = None) -> float:
        start, end = day_bounds(now or utcnow(), self.tz)
        rows = await self.llm_usage.find({"ts": {"$gte": start, "$lt": end}})
        return float(sum(r.cost_usd for r in rows))

    async def usage_breakdown(self, now: datetime | None = None, days: int = 1) -> list[dict[str, Any]]:
        _, end = day_bounds(now or utcnow(), self.tz)
        rows = await self.llm_usage.find({"ts": {"$gte": end - timedelta(days=days), "$lt": end}})
        groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "errors": 0}
        )
        for r in rows:
            g = groups[(r.role, r.provider, r.model)]
            g["calls"] += 1
            g["input_tokens"] += r.input_tokens
            g["output_tokens"] += r.output_tokens
            g["cost_usd"] += r.cost_usd
            g["errors"] += 0 if r.ok else 1
        out = [
            {"role": k[0], "provider": k[1], "model": k[2], **v, "cost_usd": round(v["cost_usd"], 6)}
            for k, v in groups.items()
        ]
        return sorted(out, key=lambda r: -r["cost_usd"])

    # --- postlar ---

    async def get_post(self, post_id: int) -> Post | None:
        return await self.posts.get(post_id)

    async def posts_by_status(self, *statuses: str, limit: int = 50) -> list[Post]:
        return await self.posts.find(
            {"status": {"$in": list(statuses)}}, sort=[("scheduled_at", 1), ("_id", 1)], limit=limit
        )

    # --- tozalash ---

    async def cleanup_old(self, now: datetime | None = None, days: int = 90) -> int:
        cutoff = (now or utcnow()) - timedelta(days=days)
        removed = await self.qa_logs.delete_where({"ts": {"$lt": cutoff}})
        removed += await self.moderation_events.delete_where({"ts": {"$lt": cutoff}})
        return removed
