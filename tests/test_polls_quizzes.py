import json
import re
from datetime import timedelta

from sqlalchemy import select

from app.ai.types import Message
from app.db.models import Poll, Post
from app.interactive.polls import PollService
from app.interactive.quizzes import QuizService
from app.pipeline.orchestrator import Pipeline
from app.pipeline.state import PostKind, PostStatus
from app.utils.timeutil import utcnow
from tests.conftest import use_llm
from tests.fakes import ScriptedLLM

QUIZ = {
    "question": "Qaysi klaviatura yorligʻi matndan nusxa oladi?",
    "options": ["Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z"],
    "correct_index": 0,
    "explanation": "Ctrl+C — nusxa olish, Ctrl+V — qoʻyish.",
}


def shown_index(messages: list[Message], option: str) -> int:
    """Tekshiruvchiga ko'rsatilgan (aralashtirilgan) variantlar ichidan berilgan variant indeksini topadi."""
    for line in messages[-1].content.splitlines():
        m = re.match(r"^(\d+)\) (.*)$", line.strip())
        if m and m.group(2) == option:
            return int(m.group(1))
    raise AssertionError("variant topilmadi")


def verify_answer(option: str, *, confidence: float = 0.95, ambiguous: bool = False):
    def answer(messages: list[Message]) -> str:
        assert "Ctrl+C — nusxa" not in messages[-1].content  # to'g'ri javob ko'rsatilmaydi
        return json.dumps(
            {
                "answer_index": shown_index(messages, option),
                "confidence": confidence,
                "ambiguous": ambiguous,
                "reason": "r",
            }
        )

    return answer


def services(ctx):
    ctx.services["pipeline"] = Pipeline(ctx)
    return QuizService(ctx), PollService(ctx)


async def test_quiz_verified_matches(ctx) -> None:
    writer = ScriptedLLM(script=[json.dumps(QUIZ)])
    editor = ScriptedLLM(script=[verify_answer("Ctrl+C")])
    use_llm(ctx, writer=writer, editor=editor)
    quizzes, _ = services(ctx)
    pid = await quizzes.create("klaviatura yorliqlari")
    post = await ctx.repo.get_post(pid)
    assert post.kind == PostKind.QUIZ
    assert post.status == PostStatus.PENDING_APPROVAL
    poll = post.extra["poll"]
    assert poll["quiz"] is True and poll["options"][poll["correct_option_id"]] == "Ctrl+C"
    async with ctx.repo.session() as s:
        row = (await s.execute(select(Poll))).scalar_one()
    assert row.purpose == "quiz" and row.correct_option_ids == [poll["correct_option_id"]]


async def test_quiz_dropped_on_mismatch(ctx) -> None:
    writer = ScriptedLLM(script=[json.dumps(QUIZ)] * 2)
    editor = ScriptedLLM(script=[verify_answer("Ctrl+V")] * 2)
    use_llm(ctx, writer=writer, editor=editor)
    quizzes, _ = services(ctx)
    assert await quizzes.create("klaviatura yorliqlari") is None
    assert len(editor.calls) == 2
    async with ctx.repo.session() as s:
        assert (await s.execute(select(Post))).first() is None
    assert ctx.notifier.messages


async def test_quiz_dropped_on_ambiguous_or_low_confidence(ctx) -> None:
    writer = ScriptedLLM(script=[json.dumps(QUIZ)] * 2)
    editor = ScriptedLLM(
        script=[verify_answer("Ctrl+C", ambiguous=True), verify_answer("Ctrl+C", confidence=0.5)]
    )
    use_llm(ctx, writer=writer, editor=editor)
    quizzes, _ = services(ctx)
    assert await quizzes.create(None) is None


async def test_quiz_limits_enforced_before_verification(ctx) -> None:
    bad = dict(QUIZ, options=["Ctrl+C", "Ctrl+V", "Ctrl+X"])
    writer = ScriptedLLM(script=[json.dumps(bad)] * 2)
    editor = ScriptedLLM(script=[])
    use_llm(ctx, writer=writer, editor=editor)
    quizzes, _ = services(ctx)
    assert await quizzes.create(None) is None
    assert editor.calls == []


async def test_quiz_with_fallback_verifier_needs_approval_even_in_auto(ctx) -> None:
    writer = ScriptedLLM(script=[json.dumps(QUIZ), verify_answer("Ctrl+C")])
    use_llm(ctx, writer=writer, editor=None)
    await ctx.runtime.set("publish_mode", "auto")
    quizzes, _ = services(ctx)
    pid = await quizzes.create(None)
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PENDING_APPROVAL
    assert post.needs_approval is True


async def test_poll_always_anonymous_regular_poll(ctx) -> None:
    writer = ScriptedLLM(
        script=[
            json.dumps(
                {
                    "question": "Qaysi brauzerdan foydalanasiz?",
                    "options": ["Chrome", "Firefox", "Edge", "Safari"],
                }
            )
        ]
    )
    use_llm(ctx, writer=writer)
    _, polls = services(ctx)
    pid = await polls.create("brauzer", purpose="fun")
    post = await ctx.repo.get_post(pid)
    assert post.kind == PostKind.POLL
    assert post.extra["poll"]["quiz"] is False
    assert post.extra["poll"]["options"] == ["Chrome", "Firefox", "Edge", "Safari"]
    async with ctx.repo.session() as s:
        row = (await s.execute(select(Poll))).scalar_one()
    assert row.purpose == "fun"


async def test_poll_with_invalid_options_retries_then_drops(ctx) -> None:
    bad = json.dumps({"question": "Savol?", "options": ["Faqat bitta"]})
    writer = ScriptedLLM(script=[bad, bad])
    use_llm(ctx, writer=writer)
    _, polls = services(ctx)
    assert await polls.create("x", purpose="fun") is None
    assert "variant" in writer.calls[1][-1].content


async def test_poll_closed_after_24h(ctx) -> None:
    async with ctx.repo.session() as s:
        post = Post(
            kind=PostKind.POLL, status=PostStatus.PUBLISHED, text_html="q", chat_id=-1001, message_id=77
        )
        s.add(post)
        await s.flush()
        s.add(
            Poll(
                post_id=post.id,
                question="q",
                options=["a", "b"],
                purpose="fun",
                telegram_poll_id="p1",
                closes_at=utcnow() - timedelta(minutes=1),
            )
        )
        s.add(
            Poll(
                post_id=post.id,
                question="q2",
                options=["a", "b"],
                purpose="fun",
                telegram_poll_id="p2",
                closes_at=utcnow() + timedelta(hours=5),
            )
        )
        await s.commit()
    _, polls = services(ctx)
    assert await polls.close_due() == 1
    assert ctx.sender.stopped == [(-1001, 77)]
    async with ctx.repo.session() as s:
        closed = {p.telegram_poll_id: p.closed for p in (await s.execute(select(Poll))).scalars()}
    assert closed == {"p1": True, "p2": False}


async def test_poll_results_saved_and_research_context(ctx) -> None:
    async with ctx.repo.session() as s:
        s.add(
            Poll(
                question="Qaysi OS dan foydalanasiz?",
                options=["Windows", "Linux"],
                purpose="research",
                telegram_poll_id="p9",
            )
        )
        await s.commit()
    _, polls = services(ctx)
    await polls.on_poll_update("p9", [("Windows", 30), ("Linux", 10)], total=40, is_closed=True)
    async with ctx.repo.session() as s:
        row = (await s.execute(select(Poll))).scalar_one()
    assert row.results == {"Windows": 30, "Linux": 10}
    assert row.total_voters == 40 and row.closed is True
    context = await polls.research_context()
    assert "Qaysi OS" in context and "Windows 75%" in context
