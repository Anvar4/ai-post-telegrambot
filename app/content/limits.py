"""Telegram va kontent limitlari (SPEC 4.3, 5, 6.2)."""

from __future__ import annotations

from collections.abc import Sequence

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
POLL_QUESTION_LIMIT = 300
POLL_OPTION_LIMIT = 100
QUIZ_EXPLANATION_LIMIT = 200
POLL_MIN_OPTIONS = 2
POLL_MAX_OPTIONS = 12
QUIZ_OPTIONS = 4
POST_MIN = 500
POST_MAX = 900
TITLE_SHORT_LIMIT = 60
QA_ANSWER_LIMIT = 700


def _options_errors(options: Sequence[str]) -> list[str]:
    errors: list[str] = []
    cleaned = [o.strip() for o in options]
    if any(not o for o in cleaned):
        errors.append("bo'sh variant bor")
    if len({o.lower() for o in cleaned}) != len(cleaned):
        errors.append("takrorlangan variant bor")
    for i, o in enumerate(cleaned):
        if len(o) > POLL_OPTION_LIMIT:
            errors.append(f"{i + 1}-variant {POLL_OPTION_LIMIT} belgidan uzun")
    return errors


def validate_poll(question: str, options: Sequence[str]) -> list[str]:
    errors: list[str] = []
    if not question.strip():
        errors.append("savol bo'sh")
    if len(question) > POLL_QUESTION_LIMIT:
        errors.append(f"savol {POLL_QUESTION_LIMIT} belgidan uzun")
    if not POLL_MIN_OPTIONS <= len(options) <= POLL_MAX_OPTIONS:
        errors.append(f"variantlar soni {POLL_MIN_OPTIONS}–{POLL_MAX_OPTIONS} bo'lishi kerak")
    errors.extend(_options_errors(options))
    return errors


def validate_quiz(question: str, options: Sequence[str], correct_index: int, explanation: str) -> list[str]:
    errors = validate_poll(question, options)
    if len(options) != QUIZ_OPTIONS:
        errors.append(f"testda {QUIZ_OPTIONS} ta variant bo'lishi kerak")
    if not 0 <= correct_index < len(options):
        errors.append("to'g'ri javob indeksi noto'g'ri")
    if len(explanation) > QUIZ_EXPLANATION_LIMIT:
        errors.append(f"tushuntirish {QUIZ_EXPLANATION_LIMIT} belgidan uzun")
    return errors
