import json
from datetime import UTC, datetime, timedelta

from aiogram.types import (
    Chat,
    ChatInviteLink,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    MessageReactionCountUpdated,
    PollOption,
    ReactionCount,
    ReactionTypeEmoji,
    Update,
    User,
)
from aiogram.types import (
    Poll as TgPoll,
)

from app.analytics.growth import GrowthService
from app.analytics.invites import InviteService
from app.analytics.metrics import MetricsService, engagement_score
from app.analytics.reports import ReportService
from app.bot.setup import build_dispatcher
from app.db.models import InviteLink, MemberEvent, Poll, Post, PostMetric, SubscriberSnapshot
from app.interactive.polls import PollService
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.conftest import use_llm
from tests.fakes import ScriptedLLM
from tests.tg import make_bot, msg_update, sent_texts

CHANNEL = -1002  # settings.channel_id
ADMIN = 1


def services(ctx):
    ctx.services["metrics"] = MetricsService(ctx)
    ctx.services["invites"] = InviteService(ctx)
    ctx.services["reports"] = ReportService(ctx)
    ctx.services["growth"] = GrowthService(ctx)
    ctx.services["polls"] = PollService(ctx)
    return ctx.services


async def add_published(
    ctx, *, message_id=500, chat_id=-1001, title="Post", kind=PostKind.NEWS, hours_ago=2
) -> int:
    post = Post(
        kind=kind,
        status=PostStatus.PUBLISHED,
        text_html="x",
        title_short=title,
        chat_id=chat_id,
        message_id=message_id,
        published_at=utcnow() - timedelta(hours=hours_ago),
        score=70,
    )
    await ctx.repo.add(post)
    return post.id


def test_engagement_formula() -> None:
    assert engagement_score(reactions=10, comments=5, poll_votes=20, subscribers=1000) == 40.0
    assert engagement_score(reactions=10, comments=5, poll_votes=0, subscribers=0) == 0.0


async def test_snapshot_saves_member_count(ctx) -> None:
    ctx.sender.members = 1234
    svc = services(ctx)
    await svc["metrics"].snapshot()
    snap = (await ctx.repo.all(SubscriberSnapshot))[0]
    assert snap.count == 1234


async def test_reaction_update_stored(ctx) -> None:
    svc = services(ctx)
    pid = await add_published(ctx)
    await svc["metrics"].on_reaction_count(-1001, 500, [("👍", 3), ("🔥", 2)])
    await svc["metrics"].on_reaction_count(-1001, 999, [("👍", 1)])  # noma'lum post — e'tiborsiz
    rows = await ctx.repo.all(PostMetric)
    assert len(rows) == 1
    assert rows[0].post_id == pid and rows[0].reaction_total == 5 and rows[0].reactions == {"👍": 3, "🔥": 2}


async def test_auto_forward_and_comments_counted(ctx) -> None:
    svc = services(ctx)
    pid = await add_published(ctx)
    await svc["metrics"].on_auto_forward(500, 9001)
    await svc["metrics"].on_comment(9001)
    await svc["metrics"].on_comment(9001)
    await svc["metrics"].on_comment(None)
    post = await ctx.repo.get_post(pid)
    assert post.discussion_message_id == 9001
    assert post.extra["comments"] == 2


async def test_engagement_by_post_uses_latest_subscribers(ctx) -> None:
    svc = services(ctx)
    pid = await add_published(ctx)
    ctx.sender.members = 1000
    await svc["metrics"].snapshot()
    await svc["metrics"].on_reaction_count(-1001, 500, [("👍", 10)])
    await svc["metrics"].on_auto_forward(500, 9001)
    for _ in range(5):
        await svc["metrics"].on_comment(9001)
    assert await svc["metrics"].engagement_by_post([pid]) == {pid: 20.0}


async def test_join_via_named_link_counted_and_leave_attributed(ctx) -> None:
    svc = services(ctx)
    url = await svc["invites"].create("hamkor1")
    assert url.startswith("https://t.me/+")
    await svc["invites"].on_member_update(CHANNEL, 77, "left", "member", url)
    await svc["invites"].on_member_update(CHANNEL, 78, "left", "member", None)
    await svc["invites"].on_member_update(CHANNEL, 77, "member", "left", None)
    link = (await ctx.repo.all(InviteLink))[0]
    events = await ctx.repo.all(MemberEvent)
    assert (link.joins, link.leaves) == (1, 1)
    assert [e.event for e in events] == ["join", "join", "leave"]
    assert all("77" not in e.user_hash for e in events)


async def test_invite_stats_retention_after_7_days(ctx) -> None:
    svc = services(ctx)
    url = await svc["invites"].create("reklama")
    old = utcnow() - timedelta(days=10)
    link = (await ctx.repo.all(InviteLink))[0]
    link.joins = 2
    await ctx.repo.add(MemberEvent(ts=old, user_hash="a", event="join", invite_link_id=link.id))
    await ctx.repo.add(MemberEvent(ts=old, user_hash="b", event="join", invite_link_id=link.id))
    await ctx.repo.add(
        MemberEvent(ts=old + timedelta(days=2), user_hash="b", event="leave", invite_link_id=link.id)
    )
    stats = await svc["invites"].stats()
    assert stats[0]["name"] == "reklama" and stats[0]["url"] == url
    assert stats[0]["retained_7d"] == 1


async def test_member_updates_for_other_chats_ignored(ctx) -> None:
    svc = services(ctx)
    await svc["invites"].on_member_update(-100555, 77, "left", "member", None)
    assert await ctx.repo.all(MemberEvent) == []


async def test_daily_report_contains_numbers(ctx) -> None:
    svc = services(ctx)
    await add_published(ctx, title="Chrome yangilandi", hours_ago=1)
    await svc["metrics"].on_reaction_count(-1001, 500, [("👍", 7)])
    ctx.sender.members = 1500
    await svc["metrics"].snapshot()
    await svc["invites"].on_member_update(CHANNEL, 1, "left", "member", None)
    await ctx.repo.record_usage(role="writer", provider="p", model="m", cost_usd=0.37)
    await ctx.repo.audit("system", "error", message="x")
    text = await svc["reports"].daily()
    for needle in ("Chrome yangilandi", "7", "1500", "+1", "$0.37", "Xatolar: 1"):
        assert needle in text, needle


async def test_stats_json_has_posts_and_subscribers(ctx) -> None:
    svc = services(ctx)
    await add_published(ctx, title="A")
    ctx.sender.members = 900
    await svc["metrics"].snapshot()
    stats = await svc["reports"].stats(7)
    assert stats["subscribers"]["end"] == 900
    assert stats["posts"][0]["title"] == "A"
    assert "hour" in stats["posts"][0] and "engagement" in stats["posts"][0]


async def test_growth_prompt_has_stats_and_rules(ctx) -> None:
    editor = ScriptedLLM(script=["<b>Xulosa</b> Hammasi yaxshi."])
    use_llm(ctx, editor=editor)
    svc = services(ctx)
    await add_published(ctx, title="A")
    text = await svc["growth"].growth_report(7)
    assert "Xulosa" in text
    system, user = editor.calls[0][0].content, editor.calls[0][-1].content
    assert "nakrutka" in system.lower()
    assert user.startswith("<stats>") and '"posts"' in user


async def test_growth_report_falls_back_to_plain_stats(ctx) -> None:
    use_llm(ctx, editor=ScriptedLLM(script=[RuntimeError("x")] * 3))
    svc = services(ctx)
    text = await svc["growth"].growth_report(7)
    assert "Obunachilar" in text


async def test_ask_uses_stats_context(ctx) -> None:
    editor = ScriptedLLM(script=["Maslahat: kechqurun post qiling."])
    use_llm(ctx, editor=editor)
    svc = services(ctx)
    answer = await svc["growth"].ask("Qachon post qilgan yaxshi?")
    assert "kechqurun" in answer
    assert "<stats>" in editor.calls[0][-1].content and "<user>" in editor.calls[0][-1].content


# --- e2e: handlerlar ---


async def test_stats_link_and_plain_text_commands(ctx) -> None:
    editor = ScriptedLLM(script=["Advisor javobi"])
    use_llm(ctx, editor=editor)
    services(ctx)
    dp, bot = build_dispatcher(ctx), make_bot()
    await dp.feed_update(bot, msg_update("/stats 7", ADMIN))
    await dp.feed_update(bot, msg_update("/link hamkor", ADMIN))
    await dp.feed_update(bot, msg_update("Kanalni qanday o'stiraman?", ADMIN))
    texts = "\n".join(sent_texts(bot))
    assert "Statistika" in texts
    assert "https://t.me/+" in texts
    assert "Advisor javobi" in texts


async def test_poll_update_handler(ctx) -> None:
    services(ctx)
    await ctx.repo.add(Poll(question="q", options=["a", "b"], purpose="fun", telegram_poll_id="tp1"))
    dp, bot = build_dispatcher(ctx), make_bot()
    poll = TgPoll(
        id="tp1",
        question="q",
        options=[
            PollOption(persistent_id="1", text="a", voter_count=3),
            PollOption(persistent_id="2", text="b", voter_count=1),
        ],
        total_voter_count=4,
        is_closed=False,
        is_anonymous=True,
        type="regular",
        allows_multiple_answers=False,
        allows_revoting=True,
        members_only=False,
    )
    await dp.feed_update(bot, Update(update_id=880001, poll=poll))
    row = (await ctx.repo.all(Poll))[0]
    assert row.results == {"a": 3, "b": 1}


async def test_reaction_and_chat_member_handlers(ctx) -> None:
    svc = services(ctx)
    pid = await add_published(ctx, chat_id=CHANNEL)
    url = await svc["invites"].create("hamkor")
    dp, bot = build_dispatcher(ctx), make_bot()
    chat = Chat(id=CHANNEL, type="channel")
    await dp.feed_update(
        bot,
        Update(
            update_id=880002,
            message_reaction_count=MessageReactionCountUpdated(
                chat=chat,
                message_id=500,
                date=datetime.now(UTC),
                reactions=[ReactionCount(type=ReactionTypeEmoji(emoji="👍"), total_count=4)],
            ),
        ),
    )
    user = User(id=321, is_bot=False, first_name="New")
    creator = User(id=1, is_bot=False, first_name="Admin")
    await dp.feed_update(
        bot,
        Update(
            update_id=880003,
            chat_member=ChatMemberUpdated(
                chat=chat,
                from_user=user,
                date=datetime.now(UTC),
                old_chat_member=ChatMemberLeft(user=user),
                new_chat_member=ChatMemberMember(user=user),
                invite_link=ChatInviteLink(
                    invite_link=url,
                    creator=creator,
                    creates_join_request=False,
                    is_primary=False,
                    is_revoked=False,
                    name="hamkor",
                ),
            ),
        ),
    )
    metric = (await ctx.repo.all(PostMetric))[0]
    link = (await ctx.repo.all(InviteLink))[0]
    assert metric.post_id == pid and metric.reaction_total == 4
    assert link.joins == 1


def test_json_serializable_stats_helper() -> None:
    assert json.dumps({"a": 1})


async def test_best_times_needs_two_weeks_of_data(ctx) -> None:
    svc = services(ctx)
    await add_published(ctx, message_id=1, title="Yangi", hours_ago=24)
    assert await svc["reports"].best_times() is None
    await add_published(ctx, message_id=2, title="Eski", hours_ago=24 * 16)
    text = await svc["reports"].best_times()
    assert text is not None and "Eng faol vaqtlar" in text and "/set slots" in text


class _FakeCreator:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create(self, topic, **kw):
        self.calls.append((topic, kw.get("created_by")))
        return 1

    async def prepare_custom(self, kind, **kw):
        self.calls.append((kind, kw.get("story_title")))
        return 2


async def test_subscriber_milestone_triggers_special_post_and_quiz(ctx) -> None:
    svc = services(ctx)
    quizzes, pipeline = _FakeCreator(), _FakeCreator()
    ctx.services["quizzes"], ctx.services["pipeline"] = quizzes, pipeline
    ctx.sender.members = 990
    await svc["metrics"].snapshot()
    assert quizzes.calls == [] and pipeline.calls == []
    ctx.sender.members = 1003
    await svc["metrics"].snapshot()
    assert len(pipeline.calls) == 1 and "1000" in pipeline.calls[0][1]
    assert len(quizzes.calls) == 1 and quizzes.calls[0][1] == "admin"
    assert any("1000" in m[0] for m in ctx.notifier.messages)
    ctx.sender.members = 1010  # bir marra ikki marta nishonlanmaydi
    await svc["metrics"].snapshot()
    assert len(pipeline.calls) == 1
