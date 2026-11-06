"""AI javoblari uchun pydantic JSON sxemalari."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ISSUE_TYPES = (
    "fabricated",
    "wrong_number",
    "missing_source",
    "tone",
    "length",
    "unsafe",
    "language",
    "other",
)


class WriterOutput(BaseModel):
    title_short: str = Field(description="≤60 belgi, rasm uchun o'zbekcha sarlavha")
    text_html: str = Field(description="Telegram HTML formatidagi post")
    hashtags: list[str] = Field(default_factory=list)
    image_prompt_en: str = Field(default="", description="Inglizcha qisqa rasm prompti")


class FilterItem(BaseModel):
    id: int
    relevant: bool
    category: str = "boshqa"
    duplicate_suspect: bool = False


class FilterOutput(BaseModel):
    items: list[FilterItem] = Field(default_factory=list)


class EditorItem(BaseModel):
    id: int
    score: int = 0
    category: str = "yangilik"
    is_breaking: bool = False
    why_uz: str = ""
    risk_flags: list[str] = Field(default_factory=list)

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> int:
        try:
            return max(0, min(100, int(float(v))))
        except (TypeError, ValueError):
            return 0


class EditorOutput(BaseModel):
    items: list[EditorItem] = Field(default_factory=list)


class CheckIssue(BaseModel):
    type: str = "other"
    quote: str = ""
    fix: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _known(cls, v: Any) -> str:
        v = str(v or "other").strip().lower()
        return v if v in ISSUE_TYPES else "other"


class CheckOutput(BaseModel):
    verdict: Literal["pass", "fix", "reject"]
    issues: list[CheckIssue] = Field(default_factory=list)


class QuizDraft(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str = ""


class QuizVerify(BaseModel):
    answer_index: int
    confidence: float = 0.0
    ambiguous: bool = False
    reason: str = ""


class PollDraft(BaseModel):
    question: str
    options: list[str]
    description: str = ""


class ModerationOutput(BaseModel):
    label: Literal["ok", "spam", "ad_link", "insult", "scam", "offtopic"] = "ok"
    confidence: float = 0.0


class ImageReview(BaseModel):
    ok: bool = True
    reason: str = ""


class TipTopic(BaseModel):
    topic: str
    angle: str = ""
