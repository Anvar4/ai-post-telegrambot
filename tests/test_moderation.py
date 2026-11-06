import json

from sqlalchemy import select

from app.bot.keyboards import ModCB
from app.bot.setup import build_dispatcher
from app.db.models import ModerationEvent
from app.interactive.moderation import ModerationService
from app.interactive.qa import QAService
from tests.conftest import use_llm
from tests.fakes import ScriptedLLM
from tests.tg import callback_update, make_bot, msg_update, sent_texts

GROUP = -1003  # DISCUSSION_GROUP_ID
SPAMMER = 555


def label(lbl: str, conf: float = 0.9) -> str:
    return json.dumps({"label": lbl, "confidence": conf})


async def test_new_member_link_deleted_without_llm(ctx) -> None:
    fast = ScriptedLLM(model="gpt-6-luna", script=[])
    use_llm(ctx, fast=fast)
    mod = ModerationService(ctx)
    res = await mod.handle(GROUP, 10, SPAMMER, "Zo'r kanal: t.me/scam_channel", is_new_member_first_msg=True)
    assert res.action == "delete"
    assert ctx.sender.deleted == [(GROUP, 10)]
    assert fast.calls == []


async def test_escalation_delete_warn_mute(ctx) -> None:
    use_llm(ctx, fast=ScriptedLLM(model="gpt-6-luna", script=[label("spam")] * 3))
    mod = ModerationService(ctx)
    actions = [
        (await mod.handle(GROUP, 20 + i, SPAMMER, "Tez pul ishlash!", is_new_member_first_msg=False)).action
        for i in range(3)
    ]
    assert actions == ["delete", "warn", "mute"]
    assert len(ctx.sender.deleted) == 3
    assert ctx.sender.restricted == [(GROUP, SPAMMER)]
    assert ctx.sender.banned == []  # ban faqat admin tasdig'i bilan
    warn = [m for m in ctx.sender.sent if m.chat_id == GROUP]
    assert warn and "qoida" in warn[0].text.lower()
    admin_msgs = [m for m in ctx.sender.sent if m.chat_id == 1]
    assert admin_msgs and admin_msgs[-1].kwargs["reply_markup"] is not None


async def test_uncertain_label_is_ok(ctx) -> None:
    use_llm(ctx, fast=ScriptedLLM(model="gpt-6-luna", script=[label("insult", 0.4)]))
    res = await ModerationService(ctx).handle(
        GROUP, 30, SPAMMER, "Bu post zo'r emas", is_new_member_first_msg=False
    )
    assert res.action == "none"
    assert ctx.sender.deleted == []


async def test_offtopic_is_not_deleted(ctx) -> None:
    use_llm(ctx, fast=ScriptedLLM(model="gpt-6-luna", script=[label("offtopic")]))
    res = await ModerationService(ctx).handle(
        GROUP, 31, SPAMMER, "Futbol kim yutdi?", is_new_member_first_msg=False
    )
    assert res.action == "none"


async def test_events_logged_with_hash(ctx) -> None:
    use_llm(ctx, fast=ScriptedLLM(model="gpt-6-luna", script=[label("scam")]))
    await ModerationService(ctx).handle(
        GROUP, 40, SPAMMER, "Karta raqamingizni yuboring, yutuq!", is_new_member_first_msg=False
    )
    async with ctx.repo.session() as s:
        ev = (await s.execute(select(ModerationEvent))).scalar_one()
    assert ev.label == "scam" and ev.action == "delete"
    assert str(SPAMMER) not in ev.user_hash


async def test_daily_summary_counts(ctx) -> None:
    use_llm(ctx, fast=ScriptedLLM(model="gpt-6-luna", script=[label("spam"), label("insult")]))
    mod = ModerationService(ctx)
    await mod.handle(GROUP, 1, 1001, "spam", is_new_member_first_msg=False)
    await mod.handle(GROUP, 2, 1002, "haqorat", is_new_member_first_msg=False)
    text = await mod.daily_summary()
    assert "2" in text and "spam" in text and "insult" in text


async def test_group_message_from_stranger_is_moderated(ctx) -> None:
    use_llm(ctx, fast=ScriptedLLM(model="gpt-6-luna", script=[label("ad_link")]))
    ctx.services["moderation"] = ModerationService(ctx)
    dp, bot = build_dispatcher(ctx), make_bot()
    await dp.feed_update(
        bot, msg_update("Bizning kanalga obuna bo'ling", SPAMMER, chat_id=GROUP, chat_type="supergroup")
    )
    assert ctx.sender.deleted and ctx.sender.deleted[0][0] == GROUP


async def test_group_mention_triggers_qa_reply(ctx) -> None:
    use_llm(
        ctx,
        fast=ScriptedLLM(model="gpt-6-luna", script=[label("ok")]),
        writer=ScriptedLLM(script=["Guruhdagi javob"]),
    )
    ctx.services["moderation"] = ModerationService(ctx)
    ctx.services["qa"] = QAService(ctx)
    ctx.services["bot_username"] = "itdunyosi_bot"
    dp, bot = build_dispatcher(ctx), make_bot()
    await dp.feed_update(
        bot, msg_update("@itdunyosi_bot VPN nima?", 777, chat_id=GROUP, chat_type="supergroup")
    )
    assert "Guruhdagi javob" in sent_texts(bot)


async def test_messages_in_unknown_group_ignored(ctx) -> None:
    fast = ScriptedLLM(model="gpt-6-luna", script=[])
    use_llm(ctx, fast=fast)
    ctx.services["moderation"] = ModerationService(ctx)
    dp, bot = build_dispatcher(ctx), make_bot()
    await dp.feed_update(bot, msg_update("salom", SPAMMER, chat_id=-100999, chat_type="supergroup"))
    assert fast.calls == [] and ctx.sender.deleted == []


async def test_ban_button_requires_admin(ctx) -> None:
    ctx.services["moderation"] = ModerationService(ctx)
    dp, bot = build_dispatcher(ctx), make_bot()
    data = ModCB(action="ban", chat_id=GROUP, user_id=SPAMMER).pack()
    await dp.feed_update(bot, callback_update(data, 999))
    assert ctx.sender.banned == []
    await dp.feed_update(bot, callback_update(data, 1))
    assert ctx.sender.banned == [(GROUP, SPAMMER)]
