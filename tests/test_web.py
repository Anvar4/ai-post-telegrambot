"""Mini ilova (Telegram WebApp) API: faqat adminlar, imzo tekshiruvi, analitika, navbat, sozlamalar."""

import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.db.models import MemberEvent, Post, SubscriberSnapshot
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from app.web.server import build_web_app
from tests.conftest import make_settings

TOKEN = "42:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123"
ADMIN, STRANGER = 1, 999


def init_data(user_id: int, token: str = TOKEN, *, age: int = 0) -> str:
    data = {
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Anvar"}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def auth(user_id: int = ADMIN, **kw) -> dict[str, str]:
    return {"Authorization": f"tma {init_data(user_id, **kw)}"}


@pytest.fixture
def web_ctx(ctx, tmp_path):
    ctx.settings = make_settings(tmp_path, telegram_bot_token=TOKEN)
    ctx.services["publisher"] = Publisher(
        ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime
    )
    return ctx


async def client_for(ctx) -> TestClient:
    client = TestClient(TestServer(build_web_app(ctx)))
    await client.start_server()
    return client


async def test_index_page_is_served(web_ctx) -> None:
    client = await client_for(web_ctx)
    try:
        r = await client.get("/")
        assert r.status == 200
        html = await r.text()
        assert "telegram-web-app.js" in html and "IT Dunyosi" in html
    finally:
        await client.close()


async def test_api_requires_valid_admin_signature(web_ctx) -> None:
    client = await client_for(web_ctx)
    try:
        assert (await client.get("/api/overview")).status == 401
        assert (await client.get("/api/overview", headers=auth(ADMIN, token="1:other"))).status == 401
        assert (await client.get("/api/overview", headers=auth(ADMIN, age=2 * 86400))).status == 401
        assert (await client.get("/api/overview", headers=auth(STRANGER))).status == 403
        assert (await client.get("/api/overview", headers=auth(ADMIN))).status == 200
    finally:
        await client.close()


async def test_overview_has_channel_numbers(web_ctx) -> None:
    repo = web_ctx.repo
    now = utcnow()
    await repo.snapshots.insert(SubscriberSnapshot(ts=now - timedelta(days=3), count=100))
    await repo.snapshots.insert(SubscriberSnapshot(ts=now, count=112))
    for i in range(5):
        await repo.member_events.insert(
            MemberEvent(ts=now - timedelta(days=1), user_hash=f"u{i}", event="join")
        )
    await repo.member_events.insert(MemberEvent(ts=now - timedelta(days=1), user_hash="x", event="leave"))
    await repo.posts.insert(
        Post(
            kind=PostKind.NEWS,
            status=PostStatus.PUBLISHED,
            title_short="Chrome zaifligi",
            published_at=now - timedelta(hours=5),
            message_id=55,
            chat_id=-1001,
            extra={"comments": 3, "views": 240},
        )
    )
    client = await client_for(web_ctx)
    try:
        data = await (await client.get("/api/overview?days=7", headers=auth())).json()
    finally:
        await client.close()
    assert data["subscribers"]["now"] == 112
    assert (data["subscribers"]["joins"], data["subscribers"]["leaves"]) == (5, 1)
    assert data["totals"]["posts"] == 1 and data["totals"]["views"] == 240
    assert len(data["series"]["days"]) == 7 and sum(data["series"]["joins"]) == 5
    assert data["top_posts"][0]["title"] == "Chrome zaifligi"
    assert data["mode"] == "semi_auto"


async def test_queue_lists_and_actions(web_ctx) -> None:
    repo = web_ctx.repo
    pending = await repo.posts.insert(
        Post(
            kind=PostKind.NEWS,
            status=PostStatus.PENDING_APPROVAL,
            title_short="Kutmoqda",
            text_html="📰 Matn",
        )
    )
    other = await repo.posts.insert(
        Post(
            kind=PostKind.TIP, status=PostStatus.PENDING_APPROVAL, title_short="Maslahat", text_html="💡 Matn"
        )
    )
    client = await client_for(web_ctx)
    try:
        items = (await (await client.get("/api/posts?tab=queue", headers=auth())).json())["items"]
        assert {i["id"] for i in items} == {pending.id, other.id}
        assert items[0]["text"]  # koʻrish uchun matn
        r = await client.post(f"/api/posts/{pending.id}", json={"action": "publish"}, headers=auth())
        assert (await r.json())["ok"] is True
        r = await client.post(f"/api/posts/{other.id}", json={"action": "reject"}, headers=auth())
        assert (await r.json())["ok"] is True
        r = await client.post(f"/api/posts/{other.id}", json={"action": "publish"}, headers=auth())
        assert (await r.json())["ok"] is False  # rad etilgan post chiqmaydi
        published = (await (await client.get("/api/posts?tab=published", headers=auth())).json())["items"]
    finally:
        await client.close()
    assert (await repo.posts.get(pending.id)).status == PostStatus.PUBLISHED
    assert (await repo.posts.get(other.id)).status == PostStatus.REJECTED
    assert [p["id"] for p in published] == [pending.id]
    assert [s.chat_id for s in web_ctx.sender.sent] == [-1001]


async def test_schedule_action_uses_next_free_slot(web_ctx) -> None:
    post = await web_ctx.repo.posts.insert(
        Post(kind=PostKind.TOOL, status=PostStatus.PENDING_APPROVAL, title_short="Ilova", text_html="🧰 Matn")
    )
    client = await client_for(web_ctx)
    try:
        r = await client.post(f"/api/posts/{post.id}", json={"action": "schedule"}, headers=auth())
        assert (await r.json())["ok"] is True
    finally:
        await client.close()
    saved = await web_ctx.repo.posts.get(post.id)
    assert saved.status == PostStatus.SCHEDULED and saved.scheduled_at > utcnow() and saved.slot


async def test_settings_read_and_update(web_ctx) -> None:
    client = await client_for(web_ctx)
    try:
        data = await (await client.get("/api/settings", headers=auth())).json()
        assert data["values"]["slot_times"] == ["08:30", "13:00", "19:30"]
        assert "10:00" in data["choices"]["times"] and data["choices"]["categories"]["kiber"]

        async def put(key, value):
            return await (
                await client.post("/api/settings", json={"key": key, "value": value}, headers=auth())
            ).json()

        assert (await put("slot_times", ["09:00", "18:00"]))["ok"] is True
        assert (await put("categories", ["ai", "kiber"]))["ok"] is True
        assert (await put("polls_per_week", 4))["ok"] is True
        assert (await put("publish_mode", "auto"))["ok"] is True
        assert (await put("paused", True))["ok"] is True
        bad = await put("slot_times", ["25:00"])
        assert bad["ok"] is False and bad["error"]
        assert (await put("publish_mode", "yomon"))["ok"] is False
    finally:
        await client.close()
    rt = web_ctx.runtime
    assert await rt.get("slot_times") == ["09:00", "18:00"]
    assert await rt.get("categories") == ["kiber", "ai"]
    assert await rt.get("polls_per_week") == 4
    assert await rt.publish_mode() == "auto"
    assert await rt.paused() is True


async def test_stranger_cannot_change_settings(web_ctx) -> None:
    client = await client_for(web_ctx)
    try:
        r = await client.post("/api/settings", json={"key": "paused", "value": True}, headers=auth(STRANGER))
        assert r.status == 403
    finally:
        await client.close()
    assert await web_ctx.runtime.paused() is False
