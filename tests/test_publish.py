from datetime import timedelta
from pathlib import Path

from app.db.models import Poll, Post
from app.pipeline.compose import compose
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.conftest import make_settings
from tests.fakes import FakeNotifier, FakeSender

PNG = b"\x89PNG-fake"


async def add_post(ctx, **kw) -> int:
    values = {
        "kind": PostKind.NEWS,
        "status": PostStatus.SCHEDULED,
        "text_html": "📰 <b>Sarlavha</b>\n\nMatn.",
        "title_short": "Sarlavha",
        "scheduled_at": utcnow() - timedelta(minutes=1),
        "publish_key": None,
    }
    values.update(kw)
    async with ctx.repo.session() as s:
        post = Post(**values)
        s.add(post)
        await s.commit()
        return post.id


def publisher(ctx, **kw) -> Publisher:
    return Publisher(ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime, **kw)


async def test_dry_run_targets_test_channel(ctx) -> None:
    pid = await add_post(ctx)
    assert await publisher(ctx).publish(pid) is True
    assert [s.chat_id for s in ctx.sender.sent] == [-1001]
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PUBLISHED
    assert post.message_id == ctx.sender.sent[0].message_id
    assert post.chat_id == -1001
    assert post.published_at is not None


async def test_live_mode_targets_real_channel(ctx, tmp_path: Path) -> None:
    ctx.settings = make_settings(tmp_path, dry_run=False)
    pid = await add_post(ctx)
    await publisher(ctx).publish(pid)
    assert ctx.sender.sent[0].chat_id == -1002


async def test_no_target_chat_does_not_send(ctx, tmp_path: Path) -> None:
    ctx.settings = make_settings(tmp_path, dry_run=True, test_channel_id=None)
    pid = await add_post(ctx)
    assert await publisher(ctx).publish(pid) is False
    assert ctx.sender.sent == []
    assert ctx.notifier.messages


async def test_publish_idempotent_second_call_noop(ctx) -> None:
    pid = await add_post(ctx)
    pub = publisher(ctx)
    assert await pub.publish(pid) is True
    assert await pub.publish(pid) is True
    assert len(ctx.sender.sent) == 1


async def test_publish_only_scheduled(ctx) -> None:
    pid = await add_post(ctx, status=PostStatus.PENDING_APPROVAL)
    assert await publisher(ctx).publish(pid) is False
    assert ctx.sender.sent == []


async def test_recover_publishing_with_message_id_marks_published(ctx) -> None:
    pid = await add_post(ctx, status=PostStatus.PUBLISHING, message_id=555, chat_id=-1001)
    assert await publisher(ctx).recover_inflight() == 1
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PUBLISHED
    assert ctx.sender.sent == []


async def test_recover_publishing_without_message_id_fails_and_notifies(ctx) -> None:
    pid = await add_post(ctx, status=PostStatus.PUBLISHING)
    await publisher(ctx).recover_inflight()
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.FAILED
    assert ctx.sender.sent == []
    assert any(str(pid) in m[0] for m in ctx.notifier.messages)


async def test_short_text_with_image_single_photo(ctx, tmp_path: Path) -> None:
    img = tmp_path / "1.png"
    img.write_bytes(PNG)
    pid = await add_post(ctx, image_path=str(img))
    await publisher(ctx).publish(pid)
    assert [s.method for s in ctx.sender.sent] == ["photo"]
    assert ctx.sender.sent[0].photo == PNG
    assert "Sarlavha" in ctx.sender.sent[0].text


async def test_long_text_splits_photo_and_message(ctx, tmp_path: Path) -> None:
    img = tmp_path / "1.png"
    img.write_bytes(PNG)
    long_text = "📰 <b>Uzun</b>\n\n" + ("Matn " * 300)
    pid = await add_post(ctx, image_path=str(img), text_html=long_text, title_short="Uzun sarlavha")
    await publisher(ctx).publish(pid)
    assert [s.method for s in ctx.sender.sent] == ["photo", "message"]
    assert "Uzun sarlavha" in ctx.sender.sent[0].text
    assert ctx.sender.sent[1].text == long_text.strip()
    post = await ctx.repo.get_post(pid)
    assert post.message_id == ctx.sender.sent[0].message_id


async def test_missing_image_file_sends_text_only(ctx) -> None:
    pid = await add_post(ctx, image_path="/nope/missing.png")
    await publisher(ctx).publish(pid)
    assert [s.method for s in ctx.sender.sent] == ["message"]


async def test_failure_three_attempts_then_failed(ctx) -> None:
    ctx.sender = FakeSender(fail_times=3)
    ctx.notifier = FakeNotifier()
    pid = await add_post(ctx)
    pub = publisher(ctx)
    for _ in range(2):
        assert await pub.publish(pid) is False
        assert (await ctx.repo.get_post(pid)).status == PostStatus.SCHEDULED
    assert await pub.publish(pid) is False
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.FAILED
    assert post.attempts == 3
    assert ctx.notifier.messages


async def test_publish_due_respects_time_and_pause(ctx) -> None:
    due = await add_post(ctx, scheduled_at=utcnow() - timedelta(minutes=5))
    later = await add_post(ctx, scheduled_at=utcnow() + timedelta(hours=1))
    pub = publisher(ctx)
    await ctx.runtime.set("paused", True)
    assert await pub.publish_due(utcnow()) == 0
    await ctx.runtime.set("paused", False)
    assert await pub.publish_due(utcnow()) == 1
    assert (await ctx.repo.get_post(due)).status == PostStatus.PUBLISHED
    assert (await ctx.repo.get_post(later)).status == PostStatus.SCHEDULED


async def test_poll_post_sends_poll_and_stores_poll_id(ctx) -> None:
    pid = await add_post(
        ctx,
        kind=PostKind.QUIZ,
        text_html="Qaysi tugma nusxa oladi?",
        extra={
            "poll": {
                "question": "Qaysi tugma nusxa oladi?",
                "options": ["Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z"],
                "quiz": True,
                "correct_option_id": 0,
                "explanation": "Ctrl+C — nusxa.",
            }
        },
    )
    async with ctx.repo.session() as s:
        s.add(Poll(post_id=pid, question="Qaysi tugma nusxa oladi?", options=[], purpose="quiz"))
        await s.commit()
    await publisher(ctx).publish(pid)
    sent = ctx.sender.sent[0]
    assert sent.method == "poll"
    assert sent.kwargs["is_anonymous"] is True
    assert sent.kwargs["correct_option_id"] == 0
    async with ctx.repo.session() as s:
        from sqlalchemy import select

        poll = (await s.execute(select(Poll))).scalar_one()
    assert poll.telegram_poll_id == f"poll-{sent.message_id}"
    assert poll.closes_at is not None


async def test_share_cta_added_every_nth_post(ctx) -> None:
    await ctx.runtime.set("share_cta_every", 2)
    pub = publisher(ctx)
    for _ in range(2):
        await pub.publish(await add_post(ctx))
    assert "ulashing" not in ctx.sender.sent[0].text
    assert "ulashing" in ctx.sender.sent[1].text


def test_compose_text_only_truncates_to_limit() -> None:
    post = Post(kind=PostKind.NEWS, text_html="a" * 5000, title_short="t")
    msgs = compose(post, None)
    assert len(msgs) == 1 and msgs[0].kind == "text"
    assert len(msgs[0].text) <= 4096
