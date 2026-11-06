"""Yozuvchi (1-model) va yozish → tekshirish → tuzatish sikli."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.ai.prompts import load_prompt
from app.ai.schemas import WriterOutput
from app.ai.types import Message
from app.content.formatting import html_to_text, normalize_uz, sanitize_html, wrap_external
from app.content.hashtags import normalize_hashtags
from app.content.limits import POST_MAX, POST_MIN, TITLE_SHORT_LIMIT
from app.content.templates import render_footer, template_for
from app.pipeline.links import allowed_domains
from app.pipeline.state import PostKind

if TYPE_CHECKING:
    from app.context import AppContext
    from app.pipeline.check import Checker, CheckReport

MAX_FIX_ROUNDS = 2


@dataclass
class WriteResult:
    output: WriterOutput
    fallback_used: bool
    model: str


@dataclass
class DraftResult:
    output: WriterOutput
    report: CheckReport
    rounds: int
    writer_fallback: bool


class Writer:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def write(
        self,
        kind: PostKind | str,
        *,
        source_text: str,
        story_title: str,
        source_urls: Sequence[str],
        source_name: str | None = None,
        instructions: str | None = None,
        previous: WriterOutput | None = None,
        issues: Sequence[dict[str, str]] | None = None,
    ) -> WriteResult:
        kind = PostKind(kind)
        username = self.ctx.settings.channel_username
        if kind == PostKind.DIGEST:
            system = load_prompt("digest", template=template_for(kind, username))
        else:
            system = load_prompt(
                "writer",
                kind=kind.value,
                template=template_for(kind, username),
                min_len=POST_MIN,
                max_len=POST_MAX,
            )
        material = (
            f"Sarlavha: {story_title}\nManba: {source_name or '—'}\n"
            f"Ruxsat etilgan havolalar: {', '.join(source_urls) or '—'}\n\n{source_text}"
        )
        parts = [wrap_external("source", material)]
        if previous is not None:
            parts.append("Oldingi qoralama:\n" + wrap_external("draft", previous.text_html))
        if issues:
            parts.append(
                "Bosh muharrir topgan kamchiliklar — hammasini tuzat:\n"
                + json.dumps(list(issues), ensure_ascii=False)
            )
        if instructions:
            parts.append(f"Kanal egasining ko'rsatmasi: {instructions}")
        res = await self.ctx.router.complete(
            "writer",
            [Message("system", system, cache=True), Message("user", "\n\n".join(parts))],
            schema=WriterOutput,
            temperature=0.5,
            max_tokens=2500,
        )
        return WriteResult(
            output=self._finish(res.parsed, kind), fallback_used=res.fallback_used, model=res.model
        )

    def _finish(self, out: WriterOutput, kind: PostKind) -> WriterOutput:
        text = normalize_uz(sanitize_html(out.text_html))
        hashtags = normalize_hashtags(out.hashtags, kind)
        footer = render_footer(self.ctx.settings.channel_username)
        if footer and footer in text:
            text = text.replace(footer, "").rstrip()
        if "#" not in html_to_text(text) and hashtags:
            text = text.rstrip() + "\n" + " ".join(hashtags)
        if footer:
            text = text.rstrip() + "\n" + footer
        title = normalize_uz(html_to_text(out.title_short)).strip()[:TITLE_SHORT_LIMIT].strip()
        return WriterOutput(
            title_short=title, text_html=text, hashtags=hashtags, image_prompt_en=out.image_prompt_en.strip()
        )


async def draft_with_checks(
    writer: Writer,
    checker: Checker,
    kind: PostKind | str,
    *,
    source_text: str,
    story_title: str,
    source_urls: Sequence[str],
    source_name: str | None = None,
    has_image: bool = True,
    risk_flags: Sequence[str] = (),
    instructions: str | None = None,
    extra_allowed: Sequence[str] = (),
    max_fixes: int = MAX_FIX_ROUNDS,
) -> DraftResult:
    """Yozadi va tekshiradi; `fix` bo'lsa ≤2 marta qayta yozadi; baribir o'tmasa — admin tasdig'iga."""
    kind = PostKind(kind)
    allowed = allowed_domains([*source_urls, *extra_allowed])

    async def _write(
        previous: WriterOutput | None = None, issues: Sequence[dict[str, str]] | None = None
    ) -> WriteResult:
        return await writer.write(
            kind,
            source_text=source_text,
            story_title=story_title,
            source_urls=[*source_urls, *extra_allowed],
            source_name=source_name,
            instructions=instructions,
            previous=previous,
            issues=issues,
        )

    w = await _write()
    fallback = w.fallback_used
    report = await checker.check(
        w.output.text_html,
        source_text=source_text,
        kind=kind,
        allowed=allowed,
        has_image=has_image,
        risk_flags=risk_flags,
        source_urls=[*source_urls, *extra_allowed],
    )
    rounds = 0
    while report.verdict == "fix" and rounds < max_fixes:
        rounds += 1
        w = await _write(previous=w.output, issues=report.all_issues())
        fallback = fallback or w.fallback_used
        report = await checker.check(
            w.output.text_html,
            source_text=source_text,
            kind=kind,
            allowed=allowed,
            has_image=has_image,
            risk_flags=risk_flags,
            source_urls=[*source_urls, *extra_allowed],
        )
    if report.verdict == "fix":
        report.needs_approval = True
        report.add_reason(f"{max_fixes} marta tuzatishdan keyin ham tekshiruvdan toʻliq oʻtmadi")
    if fallback:
        report.needs_approval = True
        report.add_reason("Asosiy yozuvchi model ishlamadi — zaxira model yozdi")
    return DraftResult(output=w.output, report=report, rounds=rounds, writer_fallback=fallback)
