"""Promptlarni `app/ai/prompts/*.md` dan yuklash. O'zgaruvchilar: `{{nom}}`."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@lru_cache(maxsize=64)
def _raw(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def load_prompt(name: str, **variables: object) -> str:
    text = _raw(name)

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in variables:
            raise ValueError(f"'{name}' promptida '{key}' o'zgaruvchisi berilmagan")
        return str(variables[key])

    return _VAR_RE.sub(repl, text)
