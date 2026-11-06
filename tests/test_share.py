"""Nashrdan keyin "📤 Ulashish" tugmasi (t.me/share/url)."""

from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.db.models import Post
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.conftest import make_settings
from tests.fakes import FakeNotifier, FakeSender


async def add_post(ctx, **kw) -> int:
    values = {
        "kind": PostKind.NEWS,
        "status": PostStatus.SCHEDULED,
        "text_html": "📰 <b>Sarlavha</b>\n\nMatn.",
        "title_short": "Sarlavha",
        "scheduled_at": utcnow() - timedelta(minutes=1),
    }
    values.update(kw)
    return (await ctx.repo.posts.insert(Post(**values))).id


def publisher(ctx) -> Publisher:
    return Publisher(ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime)


def share_url(markup) -> str:
    [[button]] = markup.inline_keyboard
    assert button.text == "📤 Ulashish"
    assert button.url.startswith("https://t.me/share/url?")
    return parse_qs(urlparse(button.url).query)["url"][0]


async def test_share_button_added_after_publish(ctx) -> None:
    pid = await add_post(ctx)
    assert await publisher(ctx).publish(pid)
    [sent] = ctx.sender.sent
    [(chat_id, message_id, markup)] = ctx.sender.markups
    assert (chat_id, message_id) == (-1001, sent.message_id)
    assert share_url(markup) == f"https://t.me/c/1/{sent.message_id}"  # DRY_RUN — test kanal havolasi


async def test_share_link_uses_channel_username_in_live_mode(ctx, tmp_path: Path) -> None:
    settings = make_settings(tmp_path, dry_run=False)
    sender = FakeSender()
    pid = await add_post(ctx)
    pub = Publisher(ctx.repo, sender, settings, FakeNotifier(), runtime=ctx.runtime)
    assert await pub.publish(pid)
    [(_, message_id, markup)] = sender.markups
    assert share_url(markup) == f"https://t.me/it_dunyosi/{message_id}"


async def test_share_button_on_last_message_of_long_post(ctx, tmp_path: Path) -> None:
    img = tmp_path / "c.png"
    img.write_bytes(b"\x89PNG-fake")
    pid = await add_post(ctx, text_html="📰 " + "Uzun matn. " * 150, image_path=str(img))
    assert await publisher(ctx).publish(pid)
    first, last = ctx.sender.sent
    [(_, message_id, markup)] = ctx.sender.markups
    assert message_id == last.message_id
    assert share_url(markup).endswith(f"/{first.message_id}")


async def test_share_button_respects_setting_and_skips_polls(ctx) -> None:
    await ctx.runtime.set("share_button", False)
    assert await publisher(ctx).publish(await add_post(ctx))
    assert ctx.sender.markups == []
    await ctx.runtime.set("share_button", True)
    poll = {"question": "Qaysi?", "options": ["A", "B"], "quiz": False}
    assert await publisher(ctx).publish(await add_post(ctx, kind=PostKind.POLL, extra={"poll": poll}))
    assert ctx.sender.markups == []


async def test_share_button_failure_does_not_break_publish(ctx) -> None:
    ctx.sender.fail_markup = True
    pid = await add_post(ctx)
    assert await publisher(ctx).publish(pid)
    assert (await ctx.repo.get_post(pid)).status == PostStatus.PUBLISHED
