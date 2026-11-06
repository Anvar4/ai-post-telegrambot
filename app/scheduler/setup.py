"""APScheduler (AsyncIOScheduler + SQLAlchemyJobStore) sozlash."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.content.schedule import SLOT_NAMES
from app.context import AppContext
from app.utils.timeutil import parse_hhmm

J = "app.scheduler.jobs:"
DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DIGEST_PREPARE_MIN = 45


def _minus(hhmm: str, minutes: int) -> tuple[int, int]:
    t = (datetime.combine(date(2000, 1, 2), parse_hhmm(hhmm)) - timedelta(minutes=minutes)).time()
    return t.hour, t.minute


async def schedule_slots(ctx: AppContext, scheduler: AsyncIOScheduler) -> None:
    """Slot va dayjest vazifalarini joriy sozlamalar bo'yicha (qayta) qo'yadi."""
    tz = ZoneInfo(ctx.settings.tz)
    slots = await ctx.runtime.get("slots")
    before = int(await ctx.runtime.get("prepare_minutes_before"))
    for name in SLOT_NAMES:
        hour, minute = _minus(slots[name], before)
        scheduler.add_job(
            f"{J}slot_job",
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            args=[name],
            id=f"slot_{name}",
            replace_existing=True,
        )
    digest = await ctx.runtime.get("digest")
    hour, minute = _minus(digest["time"], DIGEST_PREPARE_MIN)
    scheduler.add_job(
        f"{J}digest_job",
        CronTrigger(day_of_week=DOW[int(digest["weekday"])], hour=hour, minute=minute, timezone=tz),
        id="digest",
        replace_existing=True,
    )


async def setup_scheduler(ctx: AppContext, *, persistent: bool = True) -> AsyncIOScheduler:
    tz = ZoneInfo(ctx.settings.tz)
    jobstore: Any
    if persistent:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

        jobstore = SQLAlchemyJobStore(url=ctx.settings.sync_database_url)
    else:
        jobstore = MemoryJobStore()
    scheduler = AsyncIOScheduler(
        jobstores={"default": jobstore},
        timezone=tz,
        job_defaults={"coalesce": True, "misfire_grace_time": 900, "max_instances": 1},
    )

    def add(func: str, trigger: Any, job_id: str, **kw: Any) -> None:
        scheduler.add_job(f"{J}{func}", trigger, id=job_id, replace_existing=True, **kw)

    soon = datetime.now(tz) + timedelta(seconds=30)
    add("collect_job", IntervalTrigger(minutes=30, timezone=tz), "collect", next_run_time=soon)
    add("score_job", CronTrigger(hour="*/2", minute=5, timezone=tz), "score")
    await schedule_slots(ctx, scheduler)
    add("publish_due_job", IntervalTrigger(minutes=1, timezone=tz), "publish_due")
    add("expire_job", IntervalTrigger(minutes=10, timezone=tz), "expire")
    add("heartbeat_job", IntervalTrigger(minutes=1, timezone=tz), "heartbeat", next_run_time=soon)
    add("cleanup_job", CronTrigger(hour=3, minute=30, timezone=tz), "cleanup")
    add("backup_job", CronTrigger(hour=3, minute=0, timezone=tz), "backup")
    add("snapshot_job", CronTrigger(hour="9,15,21", minute=0, timezone=tz), "snapshot")
    add("daily_report_job", CronTrigger(hour=21, minute=30, timezone=tz), "daily_report")
    add("weekly_report_job", CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=tz), "weekly_report")
    add("poll_close_job", IntervalTrigger(minutes=30, timezone=tz), "poll_close")
    add("qa_faq_job", CronTrigger(day_of_week="sat", hour=12, minute=0, timezone=tz), "qa_faq")
    ctx.services["scheduler"] = scheduler
    return scheduler
