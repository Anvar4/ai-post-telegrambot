from datetime import UTC, datetime

import pytest

from app.ai.pricing import cost_usd, image_cost
from app.ai.types import BudgetExceededError
from app.db.models import LLMUsage
from app.utils.budget import BudgetGuard
from tests.fakes import FakeNotifier


def test_cost_known_models() -> None:
    assert cost_usd("gpt-6-sol", 1_000_000, 0) == pytest.approx(2.0)
    assert cost_usd("gpt-6-sol", 0, 1_000_000) == pytest.approx(10.0)
    assert cost_usd("gpt-6-luna", 1_000_000, 1_000_000) == pytest.approx(0.6)


def test_cost_cached_tokens_cheaper() -> None:
    # 1M kirish, shundan 1M keshdan: 0.20$
    assert cost_usd("gpt-6-sol", 1_000_000, 0, cached_tokens=1_000_000) == pytest.approx(0.2)


def test_cost_override_and_prefix() -> None:
    prices = {"my-model": {"in": 1.0, "out": 2.0}}
    assert cost_usd("my-model", 1_000_000, 1_000_000, prices=prices) == pytest.approx(3.0)
    # dated snapshot nomi prefiks bo'yicha topiladi
    assert cost_usd("gpt-6-sol-2026-09-22", 1_000_000, 0) == pytest.approx(2.0)


def test_unknown_model_uses_conservative_default() -> None:
    assert cost_usd("totally-unknown", 1_000_000, 0) > 0


def test_image_cost_positive() -> None:
    assert image_cost("gpt-image-2") > 0


async def test_budget_states(repo) -> None:
    guard = BudgetGuard(repo, daily_budget=1.0, notifier=FakeNotifier())
    assert await guard.state() == "ok"
    await repo.record_usage(role="w", provider="p", model="m", cost_usd=0.85)
    assert await guard.state() == "warn"
    await repo.record_usage(role="w", provider="p", model="m", cost_usd=0.2)
    assert await guard.state() == "exceeded"


async def test_budget_warn_once_per_day(repo) -> None:
    notifier = FakeNotifier()
    guard = BudgetGuard(repo, daily_budget=1.0, notifier=notifier)
    await repo.record_usage(role="w", provider="p", model="m", cost_usd=0.85)
    await guard.ensure(essential=False)
    await guard.ensure(essential=False)
    assert len(notifier.messages) == 1
    assert "80%" in notifier.messages[0][0]


async def test_budget_exceeded_raises_for_non_essential_only(repo) -> None:
    notifier = FakeNotifier()
    guard = BudgetGuard(repo, daily_budget=1.0, notifier=notifier)
    await repo.record_usage(role="w", provider="p", model="m", cost_usd=1.5)
    with pytest.raises(BudgetExceededError):
        await guard.ensure(essential=False)
    await guard.ensure(essential=True)
    assert len(notifier.messages) == 1  # 100% xabari bir marta


async def test_budget_warning_resets_next_day(repo, sessionmaker) -> None:
    d1 = datetime(2026, 11, 6, 6, tzinfo=UTC)
    d2 = datetime(2026, 11, 7, 6, tzinfo=UTC)
    async with sessionmaker() as s:
        for ts in (d1, d2):
            s.add(LLMUsage(ts=ts, role="w", provider="p", model="m", cost_usd=0.9, ok=True))
        await s.commit()
    notifier = FakeNotifier()
    now = [d1]
    guard = BudgetGuard(repo, daily_budget=1.0, notifier=notifier, clock=lambda: now[0])
    await guard.ensure(essential=True)
    await guard.ensure(essential=True)
    assert len(notifier.messages) == 1
    now[0] = d2
    await guard.ensure(essential=True)
    assert len(notifier.messages) == 2
