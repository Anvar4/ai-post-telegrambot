from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.content.schedule import upcoming_slot_times
from app.context import set_ctx
from app.db.models import Post
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
        "slot_0830",
        "slot_1300",
        "slot_1930",
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
    trig = str(scheduler.get_job("slot_0830").trigger)
    assert "hour='7'" in trig and "minute='45'" in trig
    evening = str(scheduler.get_job("slot_1930").trigger)
    assert "hour='18'" in evening and "minute='45'" in evening
    weekly = str(scheduler.get_job("weekly_report").trigger)
    assert "day_of_week='mon'" in weekly and "hour='9'" in weekly


async def test_custom_slot_time_from_runtime(ctx) -> None:
    await ctx.runtime.set("slot_times", ["09:10", "13:00", "19:30"])
    scheduler = await setup_scheduler(ctx, persistent=False)
    trig = str(scheduler.get_job("slot_0910").trigger)
    assert "hour='8'" in trig and "minute='25'" in trig
    assert scheduler.get_job("slot_0830") is None


async def test_reschedule_drops_removed_times(ctx) -> None:
    from app.scheduler.setup import schedule_slots

    scheduler = await setup_scheduler(ctx, persistent=False)
    await ctx.runtime.set("slot_times", ["08:30", "10:00"])
    await schedule_slots(ctx, scheduler)
    ids = {j.id for j in scheduler.get_jobs() if j.id.startswith("slot_")}
    assert ids == {"slot_0830", "slot_1000"}


async def test_stale_slot_job_removes_itself(ctx) -> None:
    class Pipe:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def prepare_slot(self, slot_time, scheduled_at):
            self.calls.append(slot_time)

    scheduler = await setup_scheduler(ctx, persistent=False)
    scheduler.add_job(
        f"{jobs.__name__}:slot_job", "interval", minutes=60, args=["morning"], id="slot_morning"
    )
    ctx.services["pipeline"] = pipe = Pipe()
    set_ctx(ctx)
    try:
        await jobs.slot_job("morning")  # eski versiyadan qolgan vazifa
        await jobs.slot_job("13:00")
    finally:
        set_ctx(None)
    assert scheduler.get_job("slot_morning") is None
    assert pipe.calls == ["13:00"]


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
    rows = await ctx.repo.audit_log.find({"action": "error"})
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
    times = upcoming_slot_times(now, ["08:30", "13:00", "19:30"])
    assert times[0] == datetime(2026, 11, 6, 13, 0, tzinfo=TZ)
    assert times[1] == datetime(2026, 11, 6, 19, 30, tzinfo=TZ)
    assert times[2] == datetime(2026, 11, 7, 8, 30, tzinfo=TZ)


async def test_digest_uses_published_posts_with_links(ctx) -> None:
    llms = make_llms(ctx)
    now = datetime(2026, 11, 8, 19, 15, tzinfo=TZ)
    for i in range(4):
        await ctx.repo.add(
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
