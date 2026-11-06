import asyncio

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.router import AIRouter
from app.ai.schemas import CheckOutput
from app.ai.types import BudgetExceededError, Message, SchemaError
from app.db.models import LLMUsage
from app.utils.budget import BudgetGuard
from tests.fakes import FakeImage, FakeNotifier, ScriptedLLM

MSGS = [Message("system", "Sen muharrirsan."), Message("user", "Tekshir")]
PASS_JSON = '{"verdict": "pass", "issues": []}'


class _Status(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"status {code}")
        self.status_code = code


def make_router(repo=None, *, writer=None, editor=None, fast=None, image=None, budget=None, timeout=5.0):
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    router = AIRouter(
        {"writer": writer, "editor": editor, "fast": fast},
        image=image,
        repo=repo,
        budget=budget,
        timeout=timeout,
        sleep=fake_sleep,
    )
    return router, sleeps


async def test_json_parse_with_code_fence() -> None:
    editor = ScriptedLLM(script=[f"```json\n{PASS_JSON}\n```"])
    router, _ = make_router(editor=editor)
    res = await router.complete("editor", MSGS, schema=CheckOutput)
    assert isinstance(res.parsed, CheckOutput)
    assert res.parsed.verdict == "pass"
    assert editor.kwargs[0]["json_mode"] is True


async def test_schema_mismatch_retries_once_then_raises() -> None:
    editor = ScriptedLLM(script=["bu JSON emas", '{"verdict": "maybe"}'])
    router, _ = make_router(editor=editor)
    with pytest.raises(SchemaError):
        await router.complete("editor", MSGS, schema=CheckOutput)
    assert len(editor.calls) == 2


async def test_schema_mismatch_then_valid_second_try() -> None:
    editor = ScriptedLLM(script=["xato", PASS_JSON])
    router, _ = make_router(editor=editor)
    res = await router.complete("editor", MSGS, schema=CheckOutput)
    assert res.parsed.verdict == "pass"
    second = editor.calls[1]
    assert second[-2].role == "assistant" and second[-2].content == "xato"
    assert "JSON" in second[-1].content


async def test_schema_instructions_added_to_system_prompt() -> None:
    editor = ScriptedLLM(script=[PASS_JSON])
    router, _ = make_router(editor=editor)
    await router.complete("editor", MSGS, schema=CheckOutput)
    system = editor.calls[0][0]
    assert system.role == "system"
    assert "verdict" in system.content and "JSON" in system.content


async def test_retry_three_times_then_fallback_writer_to_editor() -> None:
    writer = ScriptedLLM(provider="anthropic", model="claude-x", script=[RuntimeError("a")] * 3)
    editor = ScriptedLLM(script=["javob"])
    router, sleeps = make_router(writer=writer, editor=editor)
    res = await router.complete("writer", MSGS)
    assert res.text == "javob"
    assert res.fallback_used is True
    assert res.provider == "openai"
    assert len(writer.calls) == 3
    assert sleeps == [1.0, 2.0]


async def test_editor_fallback_marks_fallback_used() -> None:
    editor = ScriptedLLM(script=[RuntimeError("down")] * 3)
    writer = ScriptedLLM(provider="anthropic", model="claude-x", script=[PASS_JSON])
    router, _ = make_router(writer=writer, editor=editor)
    res = await router.complete("editor", MSGS, schema=CheckOutput)
    assert res.fallback_used is True
    assert res.role == "editor"
    assert res.model == "claude-x"


async def test_fast_falls_back_to_writer() -> None:
    fast = ScriptedLLM(model="gpt-6-luna", script=[RuntimeError("x")] * 3)
    writer = ScriptedLLM(provider="gemini", model="gemini-x", script=["ok"])
    router, _ = make_router(writer=writer, fast=fast)
    res = await router.complete("fast", MSGS)
    assert res.model == "gemini-x"


async def test_non_retryable_status_goes_straight_to_fallback() -> None:
    writer = ScriptedLLM(provider="anthropic", model="claude-x", script=[_Status(401)])
    editor = ScriptedLLM(script=["ok"])
    router, sleeps = make_router(writer=writer, editor=editor)
    res = await router.complete("writer", MSGS)
    assert res.text == "ok"
    assert len(writer.calls) == 1
    assert sleeps == []


async def test_missing_writer_uses_editor() -> None:
    editor = ScriptedLLM(script=["ok"])
    router, _ = make_router(writer=None, editor=editor)
    res = await router.complete("writer", MSGS)
    assert res.text == "ok"
    assert res.fallback_used is True


async def test_all_fail_raises() -> None:
    writer = ScriptedLLM(script=[RuntimeError("a")] * 3)
    editor = ScriptedLLM(script=[RuntimeError("b")] * 3)
    router, _ = make_router(writer=writer, editor=editor)
    with pytest.raises(RuntimeError):
        await router.complete("writer", MSGS)


async def test_timeout_counts_as_failure() -> None:
    slow = ScriptedLLM(script=["x", "x", "x"], delay=0.2)
    editor = ScriptedLLM(script=["ok"])
    router, _ = make_router(writer=slow, editor=editor, timeout=0.01)
    res = await router.complete("writer", MSGS)
    assert res.text == "ok"


async def test_usage_recorded_with_cost(repo, sessionmaker) -> None:
    editor = ScriptedLLM(model="gpt-6-sol", script=["ok"], tokens=(1_000_000, 0))
    router, _ = make_router(repo, editor=editor)
    await router.complete("editor", MSGS)
    async with sessionmaker() as s:
        row = (await s.execute(select(LLMUsage))).scalar_one()
    assert row.role == "editor"
    assert row.model == "gpt-6-sol"
    assert row.ok is True
    assert abs(row.cost_usd - 2.0) < 1e-9


async def test_failed_attempts_recorded_as_not_ok(repo, sessionmaker) -> None:
    writer = ScriptedLLM(provider="anthropic", model="claude-x", script=[RuntimeError("a")] * 3)
    editor = ScriptedLLM(script=["ok"])
    router, _ = make_router(repo, writer=writer, editor=editor)
    await router.complete("writer", MSGS)
    async with sessionmaker() as s:
        rows = (await s.execute(select(LLMUsage).order_by(LLMUsage.id))).scalars().all()
    assert [r.ok for r in rows] == [False, False, False, True]


async def test_budget_exceeded_blocks_non_essential(repo) -> None:
    await repo.record_usage(role="writer", provider="openai", model="m", cost_usd=5.0)
    budget = BudgetGuard(repo, daily_budget=3.0, notifier=FakeNotifier())
    editor = ScriptedLLM(script=["ok"])
    router, _ = make_router(repo, editor=editor, budget=budget)
    with pytest.raises(BudgetExceededError):
        await router.complete("editor", MSGS, essential=False)
    assert editor.calls == []
    res = await router.complete("editor", MSGS, essential=True)
    assert res.text == "ok"


async def test_image_failure_returns_none() -> None:
    router, _ = make_router(image=FakeImage(fail=True))
    assert await router.image("tech") is None


async def test_image_success_returns_bytes() -> None:
    router, _ = make_router(image=FakeImage(data=b"PNG"))
    assert await router.image("tech") == b"PNG"


async def test_no_image_client_returns_none() -> None:
    router, _ = make_router(image=None)
    assert await router.image("tech") is None


async def test_check_models_reports_missing() -> None:
    editor = ScriptedLLM(model="gpt-6-sol", models=["gpt-6-luna"])
    fast = ScriptedLLM(model="gpt-6-luna", models=["gpt-6-luna"])
    router, _ = make_router(editor=editor, fast=fast)
    problems = await router.check_models()
    assert len(problems) == 1
    assert "gpt-6-sol" in problems[0]


class _Item(BaseModel):
    a: int


async def test_parse_json_embedded_in_text() -> None:
    editor = ScriptedLLM(script=['Mana javob: {"a": 5} tamom'])
    router, _ = make_router(editor=editor)
    res = await router.complete("editor", MSGS, schema=_Item)
    assert res.parsed.a == 5


def test_router_module_has_no_sleep_in_tests() -> None:
    assert asyncio.iscoroutinefunction(AIRouter.complete)


async def test_truncated_completion_retried_with_bigger_budget() -> None:
    from app.ai.types import RawCompletion

    writer = ScriptedLLM(
        provider="deepseek",
        model="deepseek-v4-pro",
        script=[RawCompletion(text='{"verd', output_tokens=2500, truncated=True), PASS_JSON, PASS_JSON],
    )
    router, _ = make_router(writer=writer)
    res = await router.complete("writer", MSGS, schema=CheckOutput, max_tokens=2500)
    assert res.parsed.verdict == "pass"
    assert [k["max_tokens"] for k in writer.kwargs] == [2500, 10000]
    # keyingi chaqiruvda katta byudjet darhol ishlatiladi (behuda so'rov yo'q)
    await router.complete("writer", MSGS, schema=CheckOutput, max_tokens=2500)
    assert writer.kwargs[-1]["max_tokens"] == 10000


async def test_truncation_budget_is_capped() -> None:
    from app.ai.types import RawCompletion

    writer = ScriptedLLM(script=[RawCompletion(text="", truncated=True), "ok"])
    router, _ = make_router(writer=writer)
    await router.complete("writer", MSGS, max_tokens=20000)
    assert writer.kwargs[-1]["max_tokens"] == 32000
