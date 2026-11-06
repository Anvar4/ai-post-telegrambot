"""Tekshiruvchi (3-model): fakt-tekshiruv + kod darajasidagi qoidalar (havolalar, uzunlik, xavf)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.ai.prompts import load_prompt
from app.ai.schemas import CheckOutput
from app.ai.types import Message
from app.content.formatting import extract_links, html_to_text, visible_length, wrap_external
from app.content.limits import MESSAGE_LIMIT
from app.pipeline.links import domain_allowed, link_status
from app.pipeline.state import PostKind

if TYPE_CHECKING:
    from app.context import AppContext

NEEDS_SOURCE = frozenset({PostKind.NEWS, PostKind.ALERT, PostKind.TOOL, PostKind.SITE})
LENGTH_RULES: dict[PostKind, tuple[int, int]] = {
    PostKind.NEWS: (400, 1100),
    PostKind.ALERT: (400, 1100),
    PostKind.TOOL: (300, 1100),
    PostKind.SITE: (300, 1100),
    PostKind.TIP: (350, 1100),
    PostKind.DIGEST: (200, 1500),
    PostKind.QA: (200, 2000),
}

_UZ_WORDS = (
    "o'zbekiston",
    "ozbekiston",
    "uzbekistan",
    "toshkent",
    "tashkent",
    "uzcard",
    "humo",
    "payme",
    "uzum",
    "ucell",
    "uztelecom",
    "uzmobile",
    "beeline uz",
    ".uz",
    "узбекистан",
    "ташкент",
)
_BREACH_WORDS = (
    "buzildi",
    "buzib",
    "buzilgan",
    "xaker",
    "sizib chiq",
    "o'g'irla",
    "hujumiga uchra",
    "hack",
    "breach",
    "leak",
    "взлом",
    "утечк",
)


def detect_uz_breach(text: str) -> bool:
    t = text.lower()
    for ch in "ʻʼ’‘`":
        t = t.replace(ch, "'")
    return any(w in t for w in _UZ_WORDS) and any(w in t for w in _BREACH_WORDS)


@dataclass
class CheckReport:
    verdict: Literal["pass", "fix", "reject"]
    issues: list[dict[str, str]] = field(default_factory=list)
    code_issues: list[dict[str, str]] = field(default_factory=list)
    needs_approval: bool = False
    approval_reason: str | None = None
    degraded: bool = False
    link_notes: list[str] = field(default_factory=list)

    def add_reason(self, reason: str) -> None:
        self.approval_reason = f"{self.approval_reason}; {reason}" if self.approval_reason else reason

    def all_issues(self) -> list[dict[str, str]]:
        return [*self.code_issues, *self.issues]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "issues": self.issues,
            "code_issues": self.code_issues,
            "needs_approval": self.needs_approval,
            "approval_reason": self.approval_reason,
            "degraded": self.degraded,
            "link_notes": self.link_notes,
        }


class Checker:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def check(
        self,
        draft_html: str,
        *,
        source_text: str,
        kind: PostKind | str,
        allowed: set[str],
        has_image: bool,
        risk_flags: Sequence[str] = (),
        source_urls: Sequence[str] = (),
    ) -> CheckReport:
        kind = PostKind(kind)
        code_issues: list[dict[str, str]] = []
        notes: list[str] = []
        links = extract_links(draft_html)

        # 1) O'ylab topilgan havola — darhol rad (SPEC 12)
        foreign = [u for u in links if not domain_allowed(u, allowed)]
        if foreign:
            return CheckReport(
                verdict="reject",
                code_issues=[
                    {"type": "fabricated", "quote": u, "fix": "manbada yo'q havola"} for u in foreign
                ],
            )
        # 2) Manba havolasi
        if kind in NEEDS_SOURCE and not links:
            code_issues.append(
                {
                    "type": "missing_source",
                    "quote": "",
                    "fix": 'Manba havolasini qo\'sh: <a href="URL">Manba: nomi</a>',
                }
            )
        # 3) Uzunlik
        length = visible_length(draft_html)
        lo, hi = LENGTH_RULES.get(kind, (0, MESSAGE_LIMIT))
        if length < lo or length > min(hi, MESSAGE_LIMIT):
            code_issues.append(
                {
                    "type": "length",
                    "quote": f"{length} belgi",
                    "fix": "Post 500–900 belgi boʻlsin" if lo >= 300 else f"{lo}–{hi} belgi boʻlsin",
                }
            )
        # 4) Havolalar ishlashi
        if self.ctx.http is not None and links:
            statuses = await asyncio.gather(*(link_status(self.ctx.http, u) for u in links))
            for url, status in zip(links, statuses, strict=True):
                if status == "dead":
                    code_issues.append(
                        {
                            "type": "missing_source",
                            "quote": url,
                            "fix": "Bu havola ishlamayapti (404) — manbadagi ishlaydigan havolani qo'y",
                        }
                    )
                elif status == "unknown":
                    notes.append(f"Havolani tekshirib boʻlmadi: {url}")

        # 5) Model tekshiruvi
        url_note = (
            f"Manba havolalari (domenlari kod bilan tekshirilgan): {', '.join(source_urls)}\n\n"
            if source_urls
            else ""
        )
        user = (
            f"Post turi: {kind.value}. Uzunlik: {length} belgi (talab: 500–900).\n\n"
            + wrap_external("source", url_note + (source_text or "(manba matni yoʻq — maslahat posti)"))
            + "\n\n"
            + wrap_external("draft", draft_html)
        )
        res = await self.ctx.router.complete(
            "editor",
            [Message("system", load_prompt("factcheck"), cache=True), Message("user", user)],
            schema=CheckOutput,
            temperature=0.0,
            max_tokens=1500,
        )
        model: CheckOutput = res.parsed
        issues = [i.model_dump() for i in model.issues]
        if model.verdict == "reject":
            verdict: Literal["pass", "fix", "reject"] = "reject"
        elif model.verdict == "fix" or code_issues:
            verdict = "fix"
        else:
            verdict = "pass"
        report = CheckReport(
            verdict=verdict,
            issues=issues,
            code_issues=code_issues,
            degraded=res.fallback_used,
            link_notes=notes,
        )
        if res.fallback_used:
            report.needs_approval = True
            report.add_reason("Bosh muharrir modeli ishlamadi — tekshiruvni zaxira model qildi")
        if "uz_org_breach" in risk_flags or detect_uz_breach(html_to_text(draft_html)):
            report.needs_approval = True
            report.add_reason("Oʻzbekistondagi tashkilot buzilgani haqida xabar — admin tasdigʻi shart")
        return report
