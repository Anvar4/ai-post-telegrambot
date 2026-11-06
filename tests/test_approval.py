from datetime import timedelta

from app.bot.keyboards import ApprovalCB
from app.bot.setup import build_dispatcher
from app.db.models import Post
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.tg import callback_answers, callback_update, make_bot, msg_update, sent_texts

ADMIN, STRANGER = 1, 999


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    async def rewrite(self, post_id: int, instruction: str | None = None) -> int:
        self.calls.append(("rewrite", post_id, instruction))
        return post_id

    async def replace_text(self, post_id: int, html: str) -> None:
        self.calls.append(("replace", post_id, html))

    async def regenerate_image(self, post_id: int) -> None:
        self.calls.append(("image", post_id, None))


async def add_post(ctx, status=PostStatus.PENDING_APPROVAL, **kw) -> int:
    post = Post(kind=PostKind.NEWS, status=status, text_html="📰 <b>Matn</b>", title_short="Matn", **kw)
    await ctx.repo.add(post)
    return post.id


def cb(action: str, pid: int) -> str:
    return ApprovalCB(action=action, post_id=pid).pack()


def setup(ctx):
    ctx.services["publisher"] = Publisher(
        ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime
    )
    ctx.services["pipeline"] = FakePipeline()
    return build_dispatcher(ctx), make_bot()


async def test_callback_from_non_admin_ignored(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx)
    await dp.feed_update(bot, callback_update(cb("rej", pid), STRANGER))
    assert (await ctx.repo.get_post(pid)).status == PostStatus.PENDING_APPROVAL


async def test_reject_button_rejects(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx)
    await dp.feed_update(bot, callback_update(cb("rej", pid), ADMIN))
    assert (await ctx.repo.get_post(pid)).status == PostStatus.REJECTED


async def test_publish_button_publishes_now_to_test_channel(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx, scheduled_at=utcnow() + timedelta(hours=5))
    await dp.feed_update(bot, callback_update(cb("pub", pid), ADMIN))
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PUBLISHED
    assert [m.chat_id for m in ctx.sender.sent] == [-1001]


async def test_schedule_button_keeps_future_time(ctx) -> None:
    dp, bot = setup(ctx)
    when = utcnow() + timedelta(hours=3)
    pid = await add_post(ctx, scheduled_at=when)
    await dp.feed_update(bot, callback_update(cb("sched", pid), ADMIN))
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.SCHEDULED
    assert abs((post.scheduled_at - when).total_seconds()) < 1
    assert ctx.sender.sent == []


async def test_schedule_button_without_time_picks_next_slot(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx, scheduled_at=None)
    await dp.feed_update(bot, callback_update(cb("sched", pid), ADMIN))
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.SCHEDULED
    assert post.scheduled_at > utcnow()


async def test_callback_on_wrong_state_answers_error(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx, status=PostStatus.PUBLISHED)
    await dp.feed_update(bot, callback_update(cb("pub", pid), ADMIN))
    assert any("holat" in a for a in callback_answers(bot))
    assert ctx.sender.sent == []


async def test_edit_flow_with_instruction_calls_rewrite(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx)
    await dp.feed_update(bot, callback_update(cb("edit", pid), ADMIN))
    await dp.feed_update(bot, msg_update("qisqaroq qil", ADMIN))
    assert ctx.services["pipeline"].calls == [("rewrite", pid, "qisqaroq qil")]


async def test_edit_flow_with_ready_text_calls_replace(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx)
    ready = "<b>Yangi sarlavha</b>\n\n" + "Tayyor matn. " * 30
    await dp.feed_update(bot, callback_update(cb("edit", pid), ADMIN))
    await dp.feed_update(bot, msg_update(ready, ADMIN))
    assert ctx.services["pipeline"].calls == [("replace", pid, ready)]


async def test_edit_cancel(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx)
    await dp.feed_update(bot, callback_update(cb("edit", pid), ADMIN))
    await dp.feed_update(bot, msg_update("/cancel", ADMIN))
    await dp.feed_update(bot, msg_update("qisqaroq qil", ADMIN))
    assert ctx.services["pipeline"].calls == []
    assert any("bekor" in t.lower() for t in sent_texts(bot))


async def test_rewrite_and_image_buttons(ctx) -> None:
    dp, bot = setup(ctx)
    pid = await add_post(ctx)
    await dp.feed_update(bot, callback_update(cb("rewrite", pid), ADMIN))
    await dp.feed_update(bot, callback_update(cb("img", pid), ADMIN))
    assert [c[0] for c in ctx.services["pipeline"].calls] == ["rewrite", "image"]
