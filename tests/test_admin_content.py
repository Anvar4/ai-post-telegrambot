from datetime import timedelta

from sqlalchemy import select

from app.bot.keyboards import SourceCB
from app.bot.setup import build_dispatcher
from app.db.models import Post, Source
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.tg import callback_update, make_bot, msg_update, sent_texts

ADMIN = 1


class FakePipeline:
    def __init__(self) -> None:
        self.admin_posts: list[str] = []
        self.digests = 0

    async def prepare_from_admin(self, text: str, instructions: str | None = None) -> int:
        self.admin_posts.append(text)
        return 42

    async def prepare_digest(self, scheduled_at=None) -> int | None:
        self.digests += 1
        return None


def dispatcher(ctx):
    ctx.services["pipeline"] = FakePipeline()
    return build_dispatcher(ctx), make_bot()


async def test_post_command_calls_pipeline(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/post https://example.com/news", ADMIN))
    assert ctx.services["pipeline"].admin_posts == ["https://example.com/news"]
    await dp.feed_update(bot, msg_update("/post", ADMIN))
    assert any("Foydalanish" in t for t in sent_texts(bot))


async def test_queue_lists_pending_and_scheduled(ctx) -> None:
    async with ctx.repo.session() as s:
        s.add(
            Post(
                kind=PostKind.NEWS, status=PostStatus.PENDING_APPROVAL, text_html="a", title_short="Kutmoqda"
            )
        )
        s.add(
            Post(
                kind=PostKind.TOOL,
                status=PostStatus.SCHEDULED,
                text_html="b",
                title_short="Rejada",
                scheduled_at=utcnow() + timedelta(hours=2),
            )
        )
        s.add(Post(kind=PostKind.NEWS, status=PostStatus.PUBLISHED, text_html="c", title_short="Chiqqan"))
        await s.commit()
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/queue", ADMIN))
    text = "\n".join(sent_texts(bot))
    assert "Kutmoqda" in text and "Rejada" in text
    assert "Chiqqan" not in text


async def test_time_command_reschedules(ctx) -> None:
    async with ctx.repo.session() as s:
        post = Post(
            kind=PostKind.TOOL,
            status=PostStatus.SCHEDULED,
            text_html="b",
            title_short="R",
            scheduled_at=utcnow() + timedelta(hours=2),
        )
        s.add(post)
        await s.commit()
        pid = post.id
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update(f"/time {pid} 23:59", ADMIN))
    post = await ctx.repo.get_post(pid)
    from app.utils.timeutil import to_tz

    assert to_tz(post.scheduled_at).strftime("%H:%M") == "23:59"


async def test_sources_list_and_toggle(ctx) -> None:
    async with ctx.repo.session() as s:
        src = Source(name="Krebs", type="rss", url="https://krebs.example/feed", category="kiber", trust=5)
        s.add(src)
        await s.commit()
        sid = src.id
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/sources", ADMIN))
    assert any("Krebs" in t for t in sent_texts(bot))
    await dp.feed_update(bot, callback_update(SourceCB(action="toggle", source_id=sid).pack(), ADMIN))
    async with ctx.repo.session() as s:
        assert (await s.get(Source, sid)).enabled is False


async def test_source_add_command(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/source_add https://new.example/feed kiber", ADMIN))
    async with ctx.repo.session() as s:
        src = (await s.execute(select(Source))).scalar_one()
    assert (src.url, src.category, src.type) == ("https://new.example/feed", "kiber", "rss")


async def test_set_command_updates_and_validates(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/set slots.morning 09:00", ADMIN))
    assert (await ctx.runtime.get("slots"))["morning"] == "09:00"
    await dp.feed_update(bot, msg_update("/set slots.morning 25:99", ADMIN))
    assert (await ctx.runtime.get("slots"))["morning"] == "09:00"
    await dp.feed_update(bot, msg_update("/set approval_timeout_action publish", ADMIN))
    assert await ctx.runtime.get("approval_timeout_action") == "publish"
    await dp.feed_update(bot, msg_update("/set approval_timeout_action yomon", ADMIN))
    assert await ctx.runtime.get("approval_timeout_action") == "publish"
    await dp.feed_update(bot, msg_update("/set min_score 60", ADMIN))
    assert await ctx.runtime.get("min_score") == 60


async def test_settings_command_shows_values(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/settings", ADMIN))
    text = "\n".join(sent_texts(bot))
    assert "08:30" in text and "approval_timeout_action" in text


async def test_digest_command(ctx) -> None:
    dp, bot = dispatcher(ctx)
    await dp.feed_update(bot, msg_update("/digest", ADMIN))
    assert ctx.services["pipeline"].digests == 1
