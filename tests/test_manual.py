"""Qoʻlda post: rasm / video / matn → vaqt tanlash → bot oʻzi chiqaradi."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import Animation, MessageEntity, PhotoSize, Video

from app.bot.keyboards import ManualCB
from app.bot.setup import build_dispatcher
from app.db.models import Post
from app.pipeline.compose import compose
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import parse_when, utcnow
from tests.tg import button_data, callback_update, last_markup, make_bot, media_update, msg_update, sent_texts

ADMIN, STRANGER = 1, 999
TZ = ZoneInfo("Asia/Tashkent")


def setup(ctx):
    ctx.services["publisher"] = Publisher(
        ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime
    )
    return build_dispatcher(ctx), make_bot()


def photo() -> list[PhotoSize]:
    return [
        PhotoSize(file_id="small", file_unique_id="s", width=90, height=90),
        PhotoSize(file_id="big-photo", file_unique_id="b", width=1280, height=720),
    ]


async def only_post(ctx) -> Post:
    posts = await ctx.repo.posts.find({})
    assert len(posts) == 1
    return posts[0]


def button(bot, needle: str) -> str:
    return next(data for text, data in button_data(last_markup(bot)).items() if needle in text)


# ---------------------------------------------------------------- yaratish


async def test_photo_from_admin_starts_manual_post(ctx) -> None:
    dp, bot = setup(ctx)
    entities = [MessageEntity(type="bold", offset=0, length=5)]
    await dp.feed_update(
        bot, media_update(ADMIN, photo=photo(), caption="Salom dunyo", caption_entities=entities)
    )
    post = await only_post(ctx)
    assert post.kind == PostKind.MANUAL
    assert post.status == PostStatus.PENDING_APPROVAL
    assert post.created_by == "admin"
    assert post.text_html == "<b>Salom</b> dunyo"
    assert post.extra["media"] == {"type": "photo", "file_id": "big-photo"}
    texts = list(button_data(last_markup(bot)))
    assert any("Hozir" in t for t in texts)
    assert any("Boshqa vaqt" in t for t in texts)
    assert any("Bekor" in t for t in texts)
    assert sum(t.startswith("🕒") for t in texts) == 3  # keyingi 3 ta boʻsh slot
    assert ctx.sender.sent == []  # kanalga hali hech narsa ketmadi


async def test_video_and_animation_are_accepted(ctx) -> None:
    dp, bot = setup(ctx)
    video = Video(file_id="vid-1", file_unique_id="v", width=640, height=360, duration=12)
    gif = Animation(file_id="gif-1", file_unique_id="g", width=320, height=240, duration=3)
    await dp.feed_update(bot, media_update(ADMIN, video=video))
    await dp.feed_update(bot, media_update(ADMIN, animation=gif, caption="GIF"))
    posts = await ctx.repo.posts.find({}, sort=[("_id", 1)])
    assert [p.extra["media"] for p in posts] == [
        {"type": "video", "file_id": "vid-1"},
        {"type": "animation", "file_id": "gif-1"},
    ]
    assert posts[0].text_html == ""
    assert posts[0].title_short  # navbatda koʻrinadigan nom boʻsh emas


async def test_media_from_non_admin_ignored(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, media_update(STRANGER, photo=photo(), caption="spam"))
    assert await ctx.repo.posts.count({}) == 0


async def test_album_is_rejected_once_without_creating_posts(ctx) -> None:
    dp, bot = setup(ctx)
    for _ in range(3):
        await dp.feed_update(bot, media_update(ADMIN, photo=photo(), media_group_id="album-1"))
    assert await ctx.repo.posts.count({}) == 0
    replies = [t for t in sent_texts(bot) if "lbom" in t]
    assert len(replies) == 1


async def test_new_command_text_post_with_custom_time(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, msg_update("/new", ADMIN))
    await dp.feed_update(bot, msg_update("Bugun kechqurun jonli efir boʻladi!", ADMIN))
    post = await only_post(ctx)
    assert post.kind == PostKind.MANUAL
    assert post.text_html == "Bugun kechqurun jonli efir boʻladi!"
    assert "media" not in post.extra

    await dp.feed_update(bot, callback_update(button(bot, "Boshqa vaqt"), ADMIN))
    await dp.feed_update(bot, msg_update("ertaga kechqurun", ADMIN))  # notoʻgʻri — qayta soʻraydi
    assert (await ctx.repo.get_post(post.id)).status == PostStatus.PENDING_APPROVAL
    target = (datetime.now(TZ) + timedelta(days=2)).replace(hour=21, minute=15, second=0, microsecond=0)
    await dp.feed_update(bot, msg_update(target.strftime("%d.%m 21:15"), ADMIN))
    post = await ctx.repo.get_post(post.id)
    assert post.status == PostStatus.SCHEDULED
    assert post.scheduled_at == target
    assert post.slot is None  # oʻz vaqti — AI sloti band qilinmaydi


async def test_admin_plain_text_without_new_is_not_a_post(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, msg_update("oddiy savol", ADMIN))
    assert await ctx.repo.posts.count({}) == 0


# ---------------------------------------------------------------- vaqt va nashr


async def test_manual_post_scheduled_and_published_with_file_id(ctx) -> None:
    dp, bot = setup(ctx)
    video = Video(file_id="vid-1", file_unique_id="v", width=640, height=360, duration=12)
    await dp.feed_update(bot, media_update(ADMIN, video=video, caption="Video post"))
    post = await only_post(ctx)
    slot_cb = button(bot, "🕒")
    when = datetime.fromtimestamp(ManualCB.unpack(slot_cb).ts, UTC)
    await dp.feed_update(bot, callback_update(slot_cb, ADMIN))

    post = await ctx.repo.get_post(post.id)
    assert post.status == PostStatus.SCHEDULED
    assert post.scheduled_at == when
    assert post.slot  # AI shu slotga alohida post tayyorlamaydi
    assert ctx.sender.sent == []

    assert await ctx.services["publisher"].publish_due(now=when + timedelta(seconds=30)) == 1
    [sent] = ctx.sender.sent
    assert (sent.method, sent.chat_id, sent.text) == ("media", -1001, "Video post")
    assert sent.kwargs["media_type"] == "video"
    assert sent.kwargs["file_id"] == "vid-1"
    post = await ctx.repo.get_post(post.id)
    assert post.status == PostStatus.PUBLISHED
    assert post.message_id == sent.message_id


async def test_now_button_publishes_immediately(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, media_update(ADMIN, photo=photo(), caption="Hozir"))
    post = await only_post(ctx)
    await dp.feed_update(bot, callback_update(button(bot, "Hozir"), ADMIN))
    assert (await ctx.repo.get_post(post.id)).status == PostStatus.PUBLISHED
    assert [(s.method, s.kwargs["file_id"]) for s in ctx.sender.sent] == [("media", "big-photo")]


async def test_cancel_button_rejects(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, media_update(ADMIN, photo=photo()))
    post = await only_post(ctx)
    await dp.feed_update(bot, callback_update(button(bot, "Bekor"), ADMIN))
    assert (await ctx.repo.get_post(post.id)).status == PostStatus.REJECTED
    assert ctx.sender.sent == []


async def test_past_slot_button_is_refused(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, media_update(ADMIN, photo=photo()))
    post = await only_post(ctx)
    old = ManualCB(action="at", post_id=post.id, ts=int((utcnow() - timedelta(hours=1)).timestamp())).pack()
    await dp.feed_update(bot, callback_update(old, ADMIN))
    assert (await ctx.repo.get_post(post.id)).status == PostStatus.PENDING_APPROVAL


async def test_show_manual_post_previews_media_with_time_buttons(ctx) -> None:
    dp, bot = setup(ctx)
    await dp.feed_update(bot, media_update(ADMIN, photo=photo(), caption="Koʻrish"))
    post = await only_post(ctx)
    await dp.feed_update(bot, msg_update(f"/show {post.id}", ADMIN))
    media, info = ctx.sender.sent
    assert (media.method, media.chat_id, media.kwargs["file_id"], media.text) == (
        "media",
        ADMIN,
        "big-photo",
        "Koʻrish",
    )
    texts = [b.text for row in info.kwargs["reply_markup"].inline_keyboard for b in row]
    assert any("Hozir" in t for t in texts)
    assert not any("Qayta yozish" in t for t in texts)  # AI tugmalari qoʻlda postga kerak emas


# ---------------------------------------------------------------- kompozitsiya


def test_long_caption_split() -> None:
    text = ("Matn " * 300).strip()  # 1024 dan uzun
    post = Post(kind=PostKind.MANUAL, text_html=text, extra={"media": {"type": "photo", "file_id": "f1"}})
    msgs = compose(post, None)
    assert [m.kind for m in msgs] == ["media", "text"]
    assert msgs[0].text is None
    assert msgs[0].media == {"type": "photo", "file_id": "f1"}
    assert msgs[1].text == text


def test_short_caption_single_media() -> None:
    post = Post(
        kind=PostKind.MANUAL, text_html="Qisqa", extra={"media": {"type": "animation", "file_id": "g"}}
    )
    [msg] = compose(post, None)
    assert (msg.kind, msg.text, msg.media) == ("media", "Qisqa", {"type": "animation", "file_id": "g"})


async def test_long_caption_published_as_media_then_text(ctx) -> None:
    text = ("Uzun " * 300).strip()
    post = await ctx.repo.posts.insert(
        Post(
            kind=PostKind.MANUAL,
            status=PostStatus.SCHEDULED,
            text_html=text,
            created_by="admin",
            scheduled_at=utcnow(),
            extra={"media": {"type": "video", "file_id": "v9"}},
        )
    )
    pub = Publisher(ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime)
    assert await pub.publish(post.id)
    assert [(s.method, s.text) for s in ctx.sender.sent] == [("media", None), ("message", text)]
    assert (await ctx.repo.get_post(post.id)).message_id == ctx.sender.sent[0].message_id


# ---------------------------------------------------------------- vaqtni oʻqish


def test_parse_when() -> None:
    now = datetime(2026, 11, 6, 10, 0, tzinfo=TZ)
    assert parse_when("12:30", now) == datetime(2026, 11, 6, 12, 30, tzinfo=TZ)
    assert parse_when("08:00", now) == datetime(2026, 11, 7, 8, 0, tzinfo=TZ)  # oʻtgan — ertaga
    assert parse_when("07.11 9:05", now) == datetime(2026, 11, 7, 9, 5, tzinfo=TZ)
    assert parse_when("02.01 10:00", now) == datetime(2027, 1, 2, 10, 0, tzinfo=TZ)  # yangi yil
    assert parse_when("06.11.2026 18:00", now) == datetime(2026, 11, 6, 18, 0, tzinfo=TZ)
    for bad in ("25:00", "31.02 10:00", "ertaga", "", "06.11.2025 18:00"):
        assert parse_when(bad, now) is None, bad
