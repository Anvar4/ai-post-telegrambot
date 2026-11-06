from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.content.schedule import upcoming_slot_times
from app.context import set_ctx
from app.db.models import AuditLog, Post
from app.pipeline.orchestrator import Pipeline
from app.pipeline.state import PostKind, PostStatus
from app.scheduler import jobs
from app.scheduler.setup import setup_scheduler
from tests.pipeline_helpers import make_llms

TZ = ZoneInfo("Asia/Tashkent")


async def test_scheduler_registers_all_jobs(ctx) -> None:
    scheduler = await setup_scheduler(ctx, persistent=False)
    ids = {j.id for j in scheduler.get_jobs()}
    assert {
        "collect",
        "score",
        "slot_morning",
        "slot_midday",
        "slot_evening",
        "publish_due",
        "expire",
        "digest",
        "heartbeat",
        "cleanup",
        "backup",
        "snapshot",
        "daily_report",
        "weekly_report",
        "poll_close",
    } <= ids


async def test_slot_prepare_time_is_45_min_before(ctx) -> None:
    scheduler = await setup_scheduler(ctx, persistent=False)
    trig = str(scheduler.get_job("slot_morning").trigger)
    assert "hour='7'" in trig and "minute='45'" in trig
    evening = str(scheduler.get_job("slot_evening").trigger)
    assert "hour='18'" in evening and "minute='45'" in evening
    weekly = str(scheduler.get_job("weekly_report").trigger)
    assert "day_of_week='mon'" in weekly and "hour='9'" in weekly


async def test_custom_slot_time_from_runtime(ctx) -> None:
    await ctx.runtime.set("slots", {"morning": "09:10", "midday": "13:00", "evening": "19:30"})
    scheduler = await setup_scheduler(ctx, persistent=False)
    trig = str(scheduler.get_job("slot_morning").trigger)
    assert "hour='8'" in trig and "minute='25'" in trig


async def test_job_errors_are_reported(ctx) -> None:
    class Boom:
        async def run_once(self):
            raise RuntimeError("manba portladi")

    ctx.services["collector"] = Boom()
    set_ctx(ctx)
    try:
        await jobs.collect_job()  # xato tashqariga chiqmaydi
    finally:
        set_ctx(None)
    assert any("collect" in m[0] for m in ctx.notifier.messages)
    async with ctx.repo.session() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "error"))).scalars().all()
    assert rows and "manba portladi" in rows[0].details["message"]


async def test_missing_service_job_is_noop(ctx) -> None:
    set_ctx(ctx)
    try:
        await jobs.snapshot_job()
        await jobs.daily_report_job()
    finally:
        set_ctx(None)
    assert ctx.notifier.messages == []


def test_upcoming_slot_times() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=TZ)
    slots = {"morning": "08:30", "midday": "13:00", "evening": "19:30"}
    times = upcoming_slot_times(now, slots)
    assert times[0] == datetime(2026, 11, 6, 13, 0, tzinfo=TZ)
    assert times[1] == datetime(2026, 11, 6, 19, 30, tzinfo=TZ)
    assert times[2] == datetime(2026, 11, 7, 8, 30, tzinfo=TZ)


async def test_digest_uses_published_posts_with_links(ctx) -> None:
    llms = make_llms(ctx)
    now = datetime(2026, 11, 8, 19, 15, tzinfo=TZ)
    async with ctx.repo.session() as s:
        for i in range(4):
            s.add(
                Post(
                    kind=PostKind.NEWS,
                    status=PostStatus.PUBLISHED,
                    text_html="x",
                    title_short=f"Post {i}",
                    message_id=100 + i,
                    chat_id=-1002,
                    published_at=now.astimezone(UTC) - timedelta(days=1),
                    score=60 + i,
                )
            )
        await s.commit()
    p = Pipeline(ctx, clock=lambda: now.astimezone(UTC))
    pid = await p.prepare_digest(datetime(2026, 11, 8, 20, 0, tzinfo=TZ))
    post = await ctx.repo.get_post(pid)
    assert post.kind == PostKind.DIGEST
    assert post.status == PostStatus.PENDING_APPROVAL
    writer_user = llms["writer"].calls[-1][-1].content
    assert "https://t.me/it_dunyosi/103" in writer_user
    assert "Post 3" in writer_user


async def test_digest_skipped_with_too_few_posts(ctx) -> None:
    make_llms(ctx)
    now = datetime(2026, 11, 8, 19, 15, tzinfo=TZ)
    p = Pipeline(ctx, clock=lambda: now.astimezone(UTC))
    assert await p.prepare_digest(datetime(2026, 11, 8, 20, 0, tzinfo=TZ)) is None
