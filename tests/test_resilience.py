"""Tarmoq uzilishi (MongoDB/Telegram/internet) — xato emas: adminga spam yoʻq, post FAILED boʻlmaydi."""

from datetime import timedelta

import httpx
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError

from app.context import set_ctx
from app.db.models import Post
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from app.scheduler import jobs
from app.utils.neterrors import is_transient
from app.utils.outage import OutageTracker, get_tracker
from app.utils.timeutil import utcnow


def test_transient_errors_are_recognised() -> None:
    assert is_transient(AutoReconnect("ac-x.mongodb.net:27017: [Errno 11001] getaddrinfo failed"))
    assert is_transient(ServerSelectionTimeoutError("no servers"))
    assert is_transient(httpx.ConnectError("dns"))
    assert is_transient(TelegramNetworkError(method=SendMessage(chat_id=1, text="x"), message="timeout"))
    assert is_transient(OSError(11001, "getaddrinfo failed"))
    assert is_transient(TimeoutError())
    assert not is_transient(ValueError("bug"))
    assert not is_transient(KeyError("x"))


async def run_job(ctx, exc: BaseException | None) -> None:
    class Collector:
        async def run_once(self):
            if exc is not None:
                raise exc
            return type("S", (), {"new_stories": 0})()

    ctx.services["collector"] = Collector()
    set_ctx(ctx)
    try:
        await jobs.collect_job()
    finally:
        set_ctx(None)


async def test_network_error_in_job_does_not_spam_admin(ctx) -> None:
    for _ in range(5):
        await run_job(ctx, AutoReconnect("getaddrinfo failed"))
    assert ctx.notifier.messages == []
    assert await ctx.repo.audit_log.count({"action": "error"}) == 0


async def test_long_outage_notifies_once_and_recovery_is_reported(ctx) -> None:
    await run_job(ctx, AutoReconnect("getaddrinfo failed"))
    tracker = get_tracker(ctx)
    tracker.started = utcnow() - timedelta(minutes=11)
    await run_job(ctx, AutoReconnect("getaddrinfo failed"))
    await run_job(ctx, AutoReconnect("getaddrinfo failed"))
    assert len(ctx.notifier.messages) == 1 and "aloqa" in ctx.notifier.messages[0][0].lower()
    await run_job(ctx, None)
    assert len(ctx.notifier.messages) == 2 and "tiklandi" in ctx.notifier.messages[1][0]
    await run_job(ctx, None)
    assert len(ctx.notifier.messages) == 2


async def test_short_outage_is_silent_even_after_recovery(ctx) -> None:
    await run_job(ctx, AutoReconnect("x"))
    await run_job(ctx, None)
    assert ctx.notifier.messages == []
    assert get_tracker(ctx).started is None


async def test_real_bug_is_still_reported(ctx) -> None:
    await run_job(ctx, ValueError("kutilmagan xato"))
    assert any("collect" in m[0] for m in ctx.notifier.messages)


async def test_tracker_without_notify_window() -> None:
    tracker = OutageTracker(notify_after=timedelta(minutes=10))
    assert tracker.started is None


async def test_network_error_while_publishing_does_not_fail_post(ctx) -> None:
    class DownSender:
        async def send_message(self, *a, **k):
            raise TelegramNetworkError(
                method=SendMessage(chat_id=1, text="x"), message="Request timeout error"
            )

    post = await ctx.repo.posts.insert(
        Post(
            kind=PostKind.NEWS,
            status=PostStatus.SCHEDULED,
            text_html="📰 Matn",
            scheduled_at=utcnow() - timedelta(minutes=1),
        )
    )
    pub = Publisher(ctx.repo, DownSender(), ctx.settings, ctx.notifier, runtime=ctx.runtime)  # type: ignore[arg-type]
    for _ in range(5):
        assert await pub.publish(post.id) is False
    saved = await ctx.repo.posts.get(post.id)
    assert saved.status == PostStatus.SCHEDULED  # internet qaytgach chiqadi
    assert saved.attempts == 0
    assert ctx.notifier.messages == []


# ---------------------------------------------------------------- Render (bepul server)


def test_render_port_and_url_are_used(monkeypatch, tmp_path) -> None:
    from app.config import Settings

    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://it-dunyosi.onrender.com")
    s = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    assert s.web_port == 10000
    assert s.webapp_url == "https://it-dunyosi.onrender.com"
    monkeypatch.setenv("WEBAPP_URL", "https://panel.example.uz")
    assert Settings(_env_file=None).webapp_url == "https://panel.example.uz"  # type: ignore[call-arg]


async def test_health_endpoint_needs_no_auth(ctx) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from app.web.server import build_web_app

    client = TestClient(TestServer(build_web_app(ctx)))
    await client.start_server()
    try:
        r = await client.get("/health")
        assert r.status == 200 and (await r.json())["ok"] is True
    finally:
        await client.close()


async def test_keepalive_pings_own_url(ctx, tmp_path) -> None:
    import respx

    from tests.conftest import make_settings

    ctx.settings = make_settings(tmp_path, webapp_url="https://bot.onrender.com", keepalive_minutes=10)
    async with httpx.AsyncClient() as http:
        ctx.http = http
        with respx.mock:
            route = respx.get("https://bot.onrender.com/health").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            set_ctx(ctx)
            try:
                await jobs.keepalive_job()
            finally:
                set_ctx(None)
    assert route.called


async def test_keepalive_job_only_when_enabled(ctx, tmp_path) -> None:
    from app.scheduler.setup import setup_scheduler
    from tests.conftest import make_settings

    assert (await setup_scheduler(ctx)).get_job("keepalive") is None
    ctx.settings = make_settings(tmp_path, webapp_url="https://bot.onrender.com", keepalive_minutes=10)
    trig = str((await setup_scheduler(ctx)).get_job("keepalive").trigger)
    assert "0:10:00" in trig
