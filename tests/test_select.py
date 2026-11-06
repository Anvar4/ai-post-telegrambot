import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Article, Post, Source, Story
from app.pipeline.select import Selector
from app.pipeline.state import PostKind, PostStatus
from tests.conftest import use_llm
from tests.fakes import ScriptedLLM

NOW = datetime(2026, 11, 6, 6, 0, tzinfo=UTC)


async def add_story(
    ctx,
    title,
    *,
    status="new",
    score=None,
    category=None,
    hours_ago=1,
    breaking=False,
    source_category="kiber",
    article_count=1,
) -> int:
    async with ctx.repo.session() as s:
        src = (await s.execute(select(Source).limit(1))).scalar_one_or_none()
        if src is None:
            src = Source(
                name="BleepingComputer", type="rss", url="https://bc.example/feed", category="kiber", trust=4
            )
            s.add(src)
            await s.flush()
        st = Story(
            title=title,
            status=status,
            score=score,
            category=category,
            source_category=source_category,
            first_seen=NOW - timedelta(hours=hours_ago),
            last_seen=NOW,
            is_breaking=breaking,
            article_count=article_count,
        )
        s.add(st)
        await s.flush()
        s.add(
            Article(
                source_id=src.id,
                url=f"https://bc.example/{st.id}",
                url_hash=f"h{st.id}",
                title=title,
                summary="Summary text",
                story_id=st.id,
            )
        )
        await s.commit()
        return st.id


async def add_post(ctx, *, title, category, days_ago=0.0, status=PostStatus.PUBLISHED) -> None:
    async with ctx.repo.session() as s:
        st = Story(
            title=title,
            status="used",
            category=category,
            first_seen=NOW - timedelta(days=days_ago),
            last_seen=NOW,
        )
        s.add(st)
        await s.flush()
        s.add(
            Post(
                kind=PostKind.NEWS,
                status=status,
                story_id=st.id,
                text_html="x",
                title_short=title,
                extra={"category": category},
                created_at=NOW - timedelta(days=days_ago),
            )
        )
        await s.commit()


def filter_json(items) -> str:
    return json.dumps({"items": items})


async def test_irrelevant_filtered_by_fast_model(ctx) -> None:
    s1 = await add_story(ctx, "Chrome zero-day exploited")
    s2 = await add_story(ctx, "Football final results")
    fast = ScriptedLLM(
        model="gpt-6-luna",
        script=[
            filter_json(
                [
                    {"id": s1, "relevant": True, "category": "kiber"},
                    {"id": s2, "relevant": False, "category": "boshqa"},
                ]
            )
        ],
    )
    editor = ScriptedLLM(
        script=[
            json.dumps(
                {
                    "items": [
                        {
                            "id": s1,
                            "score": 80,
                            "category": "kiber",
                            "is_breaking": False,
                            "why_uz": "muhim",
                            "risk_flags": [],
                        }
                    ]
                }
            )
        ]
    )
    use_llm(ctx, fast=fast, editor=editor)
    scored = await Selector(ctx, clock=lambda: NOW).score_new()
    assert scored == 1
    async with ctx.repo.session() as s:
        a, b = await s.get(Story, s1), await s.get(Story, s2)
    assert (a.status, a.score, a.category, a.why_uz) == ("scored", 80, "kiber", "muhim")
    assert b.status == "irrelevant"
    # muharrir faqat relevant story'ni ko'radi
    assert "Football" not in editor.calls[0][-1].content
    assert "<source>" in editor.calls[0][-1].content


async def test_score_each_story_once(ctx) -> None:
    s1 = await add_story(ctx, "Chrome zero-day exploited")
    fast = ScriptedLLM(
        model="gpt-6-luna", script=[filter_json([{"id": s1, "relevant": True, "category": "kiber"}])]
    )
    editor = ScriptedLLM(script=[json.dumps({"items": [{"id": s1, "score": 70}]})])
    use_llm(ctx, fast=fast, editor=editor)
    sel = Selector(ctx, clock=lambda: NOW)
    await sel.score_new()
    assert await sel.score_new() == 0
    assert len(editor.calls) == 1 and len(fast.calls) == 1


async def test_score_new_only_category_limits_to_cyber(ctx) -> None:
    s1 = await add_story(ctx, "Chrome zero-day exploited", source_category="kiber")
    await add_story(ctx, "New phone launched", source_category="yangilik")
    fast = ScriptedLLM(
        model="gpt-6-luna", script=[filter_json([{"id": s1, "relevant": True, "category": "kiber"}])]
    )
    editor = ScriptedLLM(script=[json.dumps({"items": [{"id": s1, "score": 90, "is_breaking": True}]})])
    use_llm(ctx, fast=fast, editor=editor)
    await Selector(ctx, clock=lambda: NOW).score_new(source_categories=("kiber",))
    assert "New phone" not in fast.calls[0][-1].content


async def test_pick_highest_score_in_kind_categories(ctx) -> None:
    await add_story(ctx, "Minor news", status="scored", score=60, category="yangilik")
    best = await add_story(ctx, "Big AI launch", status="scored", score=88, category="ai")
    await add_story(ctx, "Useful repo", status="scored", score=95, category="ilova")
    story = await Selector(ctx, clock=lambda: NOW).pick(PostKind.NEWS)
    assert story is not None and story.id == best


async def test_pick_min_score(ctx) -> None:
    await add_story(ctx, "Weak", status="scored", score=40, category="yangilik")
    assert await Selector(ctx, clock=lambda: NOW).pick(PostKind.NEWS) is None


async def test_pick_respects_category_daily_cap(ctx) -> None:
    await add_post(ctx, title="Kiber 1", category="kiber")
    await add_post(ctx, title="Kiber 2", category="kiber")
    await add_story(ctx, "Another ransomware wave", status="scored", score=90, category="kiber")
    other = await add_story(ctx, "Phone update", status="scored", score=60, category="yangilik")
    story = await Selector(ctx, clock=lambda: NOW).pick(PostKind.NEWS)
    assert story is not None and story.id == other


async def test_pick_skips_topic_covered_last_7_days(ctx) -> None:
    await add_post(ctx, title="Microsoft patches Exchange zero-day", category="kiber", days_ago=3)
    await add_story(
        ctx, "Microsoft patches Exchange zero-day exploited", status="scored", score=90, category="kiber"
    )
    assert await Selector(ctx, clock=lambda: NOW).pick(PostKind.NEWS) is None


async def test_pick_ignores_stories_older_than_24h_for_news(ctx) -> None:
    await add_story(ctx, "Old news", status="scored", score=90, category="yangilik", hours_ago=30)
    assert await Selector(ctx, clock=lambda: NOW).pick(PostKind.NEWS) is None


async def test_pick_tool_uses_ilova_category_with_week_window(ctx) -> None:
    tool = await add_story(
        ctx, "acme/tool: fast CLI", status="scored", score=70, category="ilova", hours_ago=72
    )
    story = await Selector(ctx, clock=lambda: NOW).pick(PostKind.TOOL)
    assert story is not None and story.id == tool


async def test_breaking_candidates(ctx) -> None:
    hot = await add_story(
        ctx, "Exploited Android flaw", status="scored", score=92, category="kiber", breaking=True
    )
    await add_story(ctx, "Breaking but low", status="scored", score=70, category="kiber", breaking=True)
    found = await Selector(ctx, clock=lambda: NOW).breaking_candidates(min_score=85)
    assert [s.id for s in found] == [hot]
