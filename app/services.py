"""Servislarni kontekstga ulash."""

from __future__ import annotations

from app.context import AppContext


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else None


def register_services(ctx: AppContext) -> None:
    """Barcha servislarni `ctx.services` ga joylaydi."""
    from app.analytics.growth import GrowthService
    from app.analytics.invites import InviteService
    from app.analytics.metrics import MetricsService
    from app.analytics.reports import ReportService
    from app.collectors.service import CollectorService
    from app.images.search import ImageSearch
    from app.interactive.moderation import ModerationService
    from app.interactive.polls import PollService
    from app.interactive.qa import QAService
    from app.interactive.quizzes import QuizService
    from app.pipeline.image import ImageStage
    from app.pipeline.orchestrator import Pipeline
    from app.pipeline.publish import Publisher
    from app.utils.backup import BackupService

    s = ctx.settings
    pipeline = Pipeline(ctx)
    ctx.services["pipeline"] = pipeline
    ctx.services["selector"] = pipeline.selector
    search = ImageSearch(ctx.http, pexels_key=_secret(s.pexels_api_key)) if ctx.http is not None else None
    ctx.services["images"] = ImageStage(ctx, search=search)
    ctx.services["polls"] = PollService(ctx)
    ctx.services["quizzes"] = QuizService(ctx)
    ctx.services["qa"] = QAService(ctx)
    ctx.services["moderation"] = ModerationService(ctx)
    ctx.services["metrics"] = MetricsService(ctx)
    ctx.services["invites"] = InviteService(ctx)
    ctx.services["reports"] = ReportService(ctx)
    ctx.services["growth"] = GrowthService(ctx)
    ctx.services["backup"] = BackupService(ctx)
    ctx.services["publisher"] = Publisher(ctx.repo, ctx.sender, s, ctx.notifier, runtime=ctx.runtime)
    if s.telethon_ready:
        from app.analytics.channel_stats import ChannelStatsService, TelethonStatsSource

        async def telethon_source() -> TelethonStatsSource:
            return await TelethonStatsSource.connect(
                int(s.tg_api_id or 0), _secret(s.tg_api_hash) or "", _secret(s.tg_session) or ""
            )

        ctx.services["channel_stats"] = ChannelStatsService(ctx, telethon_source)
    if ctx.http is not None:
        ctx.services["collector"] = CollectorService(
            ctx.repo,
            ctx.http,
            ctx.notifier,
            nvd_api_key=_secret(s.nvd_api_key),
            github_token=_secret(s.github_token),
        )
