"""Servislarni kontekstga ulash."""

from __future__ import annotations

from app.context import AppContext


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else None


def register_services(ctx: AppContext) -> None:
    """Barcha servislarni `ctx.services` ga joylaydi."""
    from app.collectors.service import CollectorService
    from app.interactive.moderation import ModerationService
    from app.interactive.polls import PollService
    from app.interactive.qa import QAService
    from app.interactive.quizzes import QuizService
    from app.pipeline.image import ImageStage
    from app.pipeline.orchestrator import Pipeline
    from app.pipeline.publish import Publisher

    s = ctx.settings
    pipeline = Pipeline(ctx)
    ctx.services["pipeline"] = pipeline
    ctx.services["selector"] = pipeline.selector
    ctx.services["images"] = ImageStage(ctx)
    ctx.services["polls"] = PollService(ctx)
    ctx.services["quizzes"] = QuizService(ctx)
    ctx.services["qa"] = QAService(ctx)
    ctx.services["moderation"] = ModerationService(ctx)
    ctx.services["publisher"] = Publisher(ctx.repo, ctx.sender, s, ctx.notifier, runtime=ctx.runtime)
    if ctx.http is not None:
        ctx.services["collector"] = CollectorService(
            ctx.repo,
            ctx.http,
            ctx.notifier,
            nvd_api_key=_secret(s.nvd_api_key),
            github_token=_secret(s.github_token),
        )
