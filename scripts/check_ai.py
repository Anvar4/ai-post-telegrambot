"""AI kalitlarini tekshirish (faqat o'qish: modellar ro'yxati so'raladi, token sarflanmaydi).

Ishlatish:  python scripts/check_ai.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.providers.factory import DEEPSEEK_BASE_URL, build_clients
from app.ai.router import AIRouter
from app.config import env_file_warnings, load_settings


def _secret(value: Any) -> str | None:
    return value.get_secret_value() if value is not None else None


async def list_models(provider: str, key: str, base_url: str | None) -> list[str]:
    if provider == "anthropic":
        from app.ai.providers.anthropic import AnthropicClient

        return await AnthropicClient(key, "?").list_models() or []
    if provider == "gemini":
        from app.ai.providers.gemini import GeminiClient

        return await GeminiClient(key, "?").list_models() or []
    from app.ai.providers.openai import OpenAIClient

    url = base_url or (DEEPSEEK_BASE_URL if provider == "deepseek" else None)
    return await OpenAIClient(key, "?", base_url=url).list_models() or []


async def main() -> int:
    s, error = load_settings()
    if s is None:
        print(error)
        return 1
    clients = build_clients(s)
    clients.problems[:0] = env_file_warnings()
    for p in clients.problems:
        print("⚠️ ", p)
    exit_code = 1 if clients.problems else 0
    openai_key = _secret(s.openai_api_key)
    if openai_key:
        try:
            models = await list_models("openai", openai_key, None)
            for m in (s.openai_editor_model, s.openai_fast_model):
                print(f"{'OK ' if m in models else 'YOʻQ'} OpenAI: {m}")
                exit_code |= m not in models
            print(f"     (kalitda {len(models)} ta model mavjud)")
        except Exception as exc:
            exit_code = 1
            print(f"XATO OpenAI kaliti: {str(exc)[:200]}")
    main_key = _secret(s.llm_main_api_key)
    if s.llm_main_provider and main_key:
        try:
            models = await list_models(s.llm_main_provider, main_key, s.llm_main_base_url)
            print(
                f"OK   1-kalit ({s.llm_main_provider}) ishlaydi. Mavjud modellar: {', '.join(sorted(models)[:25])}"
            )
            if s.llm_main_model and s.llm_main_model not in models:
                exit_code = 1
                print(f"YOʻQ LLM_MAIN_MODEL='{s.llm_main_model}' roʻyxatda topilmadi")
        except Exception as exc:
            exit_code = 1
            print(f"XATO 1-kalit ({s.llm_main_provider}): {str(exc)[:200]}")
    router = AIRouter(clients.as_roles(), image=clients.image)
    for problem in await router.check_models():
        exit_code = 1
        print("⚠️ ", problem)
    print("\n✅ Tekshiruv tugadi." if exit_code == 0 else "\n⚠️  Yuqoridagi muammolarni tuzating.")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
