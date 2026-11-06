"""Testlar uchun: mongomock (sinxron) ustidan pymongo-async ga oʻxshash yupqa adapter."""

from __future__ import annotations

from typing import Any

import mongomock


class FakeCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def sort(self, key_or_list: Any, direction: int | None = None) -> FakeCursor:
        if direction is None:
            self._cursor = self._cursor.sort(key_or_list)
        else:
            self._cursor = self._cursor.sort(key_or_list, direction)
        return self

    def limit(self, n: int) -> FakeCursor:
        self._cursor = self._cursor.limit(n)
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = list(self._cursor)
        return docs if length is None else docs[:length]

    def __aiter__(self) -> FakeCursor:
        self._iter = iter(self._cursor)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeCollection:
    def __init__(self, coll: Any) -> None:
        self._c = coll

    async def insert_one(self, doc: dict[str, Any]) -> Any:
        return self._c.insert_one(doc)

    async def insert_many(self, docs: list[dict[str, Any]], ordered: bool = True) -> Any:
        return self._c.insert_many(docs, ordered=ordered)

    async def find_one(self, filter: dict[str, Any] | None = None, *args: Any, **kwargs: Any) -> Any:
        return self._c.find_one(filter, *args, **kwargs)

    def find(self, filter: dict[str, Any] | None = None, projection: Any = None) -> FakeCursor:
        return FakeCursor(self._c.find(filter or {}, projection))

    async def replace_one(self, filter: dict[str, Any], doc: dict[str, Any], upsert: bool = False) -> Any:
        return self._c.replace_one(filter, doc, upsert=upsert)

    async def update_one(self, filter: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> Any:
        return self._c.update_one(filter, update, upsert=upsert)

    async def update_many(self, filter: dict[str, Any], update: dict[str, Any]) -> Any:
        return self._c.update_many(filter, update)

    async def delete_many(self, filter: dict[str, Any]) -> Any:
        return self._c.delete_many(filter)

    async def count_documents(self, filter: dict[str, Any]) -> int:
        return int(self._c.count_documents(filter))

    async def find_one_and_update(self, filter: dict[str, Any], update: dict[str, Any], **kwargs: Any) -> Any:
        return self._c.find_one_and_update(filter, update, **kwargs)

    async def create_index(self, keys: Any, **kwargs: Any) -> str:
        return str(self._c.create_index(keys, **kwargs))

    async def drop(self) -> None:
        self._c.drop()


class FakeDatabase:
    def __init__(self) -> None:
        self._db = mongomock.MongoClient()["test"]
        self.name = "test"

    def __getitem__(self, name: str) -> FakeCollection:
        return FakeCollection(self._db[name])

    async def list_collection_names(self) -> list[str]:
        return list(self._db.list_collection_names())

    async def command(self, name: str) -> dict[str, Any]:
        return {"ok": 1.0}
