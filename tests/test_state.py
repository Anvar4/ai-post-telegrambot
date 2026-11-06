import itertools

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, Post
from app.pipeline.state import InvalidTransitionError, PostKind, PostStatus, can_transition, transition

S = PostStatus


def test_happy_path_transitions() -> None:
    chain = [
        S.NEW,
        S.SELECTED,
        S.DRAFTED,
        S.CHECKED,
        S.PENDING_APPROVAL,
        S.SCHEDULED,
        S.PUBLISHING,
        S.PUBLISHED,
    ]
    for a, b in itertools.pairwise(chain):
        assert can_transition(a, b), f"{a} -> {b}"
    assert can_transition(S.CHECKED, S.SCHEDULED)  # auto rejim: tasdiqsiz


def test_fix_loop_allowed() -> None:
    assert can_transition(S.CHECKED, S.DRAFTED)
    assert can_transition(S.PENDING_APPROVAL, S.DRAFTED)


def test_terminal_states_locked() -> None:
    assert not can_transition(S.PUBLISHED, S.SCHEDULED)
    assert not can_transition(S.PUBLISHED, S.FAILED)
    assert not can_transition(S.REJECTED, S.SCHEDULED)
    assert not can_transition(S.EXPIRED, S.PENDING_APPROVAL)


def test_skipping_steps_not_allowed() -> None:
    assert not can_transition(S.NEW, S.PUBLISHED)
    assert not can_transition(S.DRAFTED, S.PUBLISHED)
    assert not can_transition(S.DRAFTED, S.SCHEDULED)


def test_any_nonterminal_to_failed_rejected_expired() -> None:
    for status in (S.NEW, S.SELECTED, S.DRAFTED, S.CHECKED, S.PENDING_APPROVAL, S.SCHEDULED, S.PUBLISHING):
        for end in (S.FAILED, S.REJECTED, S.EXPIRED):
            assert can_transition(status, end), f"{status} -> {end}"


def test_failed_can_be_retried() -> None:
    assert can_transition(S.FAILED, S.SCHEDULED)
    assert not can_transition(S.FAILED, S.FAILED)


async def test_transition_writes_audit(sessionmaker) -> None:
    async with sessionmaker() as session:
        post = Post(kind=PostKind.NEWS, status=S.CHECKED, text_html="x")
        session.add(post)
        await session.flush()
        await transition(session, post, S.PENDING_APPROVAL, actor="ai", reason="semi_auto")
        await session.commit()
        assert post.status == S.PENDING_APPROVAL
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "post.status"
    assert rows[0].details["from"] == "CHECKED"
    assert rows[0].details["to"] == "PENDING_APPROVAL"
    assert rows[0].details["reason"] == "semi_auto"


async def test_invalid_transition_raises(sessionmaker) -> None:
    async with sessionmaker() as session:
        post = Post(kind=PostKind.NEWS, status=S.PUBLISHED, text_html="x")
        session.add(post)
        await session.flush()
        with pytest.raises(InvalidTransitionError):
            await transition(session, post, S.SCHEDULED, actor="ai")
        assert post.status == S.PUBLISHED
