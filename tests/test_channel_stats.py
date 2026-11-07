"""Telethon kanal statistikasi: post koʻrishlari, ulashishlar, koʻrishlar manbasi."""

import json
from datetime import timedelta

from app.analytics.channel_stats import ChannelStatsService, MessageStat, graph_totals
from app.db.models import Post
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.conftest import make_settings

CHANNEL = -1002


class FakeSource:
    def __init__(self, stats=None, broadcast=None) -> None:
        self.stats = stats or []
        self.broadcast = broadcast
        self.closed = False

    async def message_stats(self, channel_id: int, limit: int) -> list[MessageStat]:
        assert channel_id == CHANNEL
        return self.stats

    async def broadcast_stats(self, channel_id: int):
        return self.broadcast

    async def close(self) -> None:
        self.closed = True


def service(ctx, source) -> ChannelStatsService:
    async def factory():
        return source

    return ChannelStatsService(ctx, factory)


def test_graph_totals_sums_each_series() -> None:
    data = json.dumps(
        {
            "columns": [["x", 1, 2, 3], ["y0", 10, 20, 30], ["y1", 1, 0, 4]],
            "names": {"y0": "Followers", "y1": "Search"},
            "types": {"x": "x", "y0": "bar", "y1": "bar"},
        }
    )
    assert graph_totals(data) == {"Followers": 60, "Search": 5}
    assert graph_totals("not json") == {}


async def test_collect_updates_views_of_published_posts(ctx, tmp_path) -> None:
    ctx.settings = make_settings(tmp_path, dry_run=False)
    post = await ctx.repo.posts.insert(
        Post(
            kind=PostKind.NEWS,
            status=PostStatus.PUBLISHED,
            title_short="Post",
            message_id=55,
            chat_id=CHANNEL,
            published_at=utcnow() - timedelta(hours=3),
            extra={"comments": 7},
        )
    )
    source = FakeSource(
        stats=[MessageStat(55, views=1520, forwards=12, replies=4, reactions=33), MessageStat(99, 5, 0, 0, 0)]
    )
    assert await service(ctx, source).collect() == 1
    extra = (await ctx.repo.posts.get(post.id)).extra
    assert (extra["views"], extra["forwards"], extra["reactions_tg"]) == (1520, 12, 33)
    assert extra["comments"] == 7  # bot sanagan izohlar kamaymaydi
    assert source.closed


async def test_collect_stores_channel_stats_with_non_follower_views(ctx, tmp_path) -> None:
    ctx.settings = make_settings(tmp_path, dry_run=False)
    broadcast = {
        "followers": {"current": 1271, "previous": 1255},
        "views_per_post": {"current": 840, "previous": 700},
        "shares_per_post": {"current": 9, "previous": 6},
        "notifications_pct": 41.5,
        "views_by_source": {"Followers": 5000, "Search": 600, "Channels": 400},
        "new_followers_by_source": {"URL": 12, "Search": 4},
    }
    await service(ctx, FakeSource(broadcast=broadcast)).collect()
    saved = await ctx.repo.get_setting("channel_stats")
    assert saved["followers"]["current"] == 1271
    assert saved["non_follower_views"] == 1000
    assert saved["updated_at"]


async def test_overview_includes_channel_stats(ctx, tmp_path) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from app.web.server import build_web_app
    from tests.test_web import TOKEN, auth

    ctx.settings = make_settings(tmp_path, telegram_bot_token=TOKEN)
    await ctx.repo.set_setting(
        "channel_stats", {"views_by_source": {"Followers": 10, "Search": 5}, "non_follower_views": 5}
    )
    client = TestClient(TestServer(build_web_app(ctx)))
    await client.start_server()
    try:
        data = await (await client.get("/api/overview", headers=auth())).json()
    finally:
        await client.close()
    assert data["channel_stats"]["non_follower_views"] == 5


def test_telethon_secrets_are_masked(tmp_path) -> None:
    settings = make_settings(
        tmp_path, tg_api_id=123, tg_api_hash="abcdef123456", tg_session="1BVtsOKABu-secret-session"
    )
    secrets = settings.secret_values()
    assert "abcdef123456" in secrets and "1BVtsOKABu-secret-session" in secrets
    assert settings.telethon_ready
    assert not make_settings(tmp_path).telethon_ready
