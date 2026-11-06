from pathlib import Path

import pytest

from app.ai.images.openai_img import OpenAIImageClient
from app.ai.prompts import load_prompt
from app.ai.providers.anthropic import AnthropicClient
from app.ai.providers.factory import build_clients
from app.ai.providers.openai import OpenAIClient
from app.ai.providers.openai_compat import OpenAICompatClient
from app.config import Settings


def settings(tmp_path: Path, text: str) -> Settings:
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    return Settings(_env_file=env)  # type: ignore[call-arg]


def test_openai_only(tmp_path: Path) -> None:
    c = build_clients(settings(tmp_path, "OPENAI_API_KEY=sk-test\n"))
    assert c.writer is None
    assert isinstance(c.editor, OpenAIClient) and c.editor.model == "gpt-6-sol"
    assert isinstance(c.fast, OpenAIClient) and c.fast.model == "gpt-6-luna"
    assert c.image is None


def test_anthropic_writer(tmp_path: Path) -> None:
    c = build_clients(
        settings(
            tmp_path,
            "OPENAI_API_KEY=sk-test\nLLM_MAIN_PROVIDER=anthropic\n"
            "LLM_MAIN_MODEL=claude-x\nLLM_MAIN_API_KEY=sk-ant-x\n",
        )
    )
    assert isinstance(c.writer, AnthropicClient)
    assert c.writer.model == "claude-x"


def test_openai_writer_falls_back_to_openai_key(tmp_path: Path) -> None:
    c = build_clients(
        settings(tmp_path, "OPENAI_API_KEY=sk-test\nLLM_MAIN_PROVIDER=openai\nLLM_MAIN_MODEL=gpt-6-sol\n")
    )
    assert isinstance(c.writer, OpenAIClient)


def test_compat_writer_requires_base_url(tmp_path: Path) -> None:
    c = build_clients(
        settings(
            tmp_path,
            "LLM_MAIN_PROVIDER=openai_compatible\nLLM_MAIN_MODEL=deepseek-chat\n"
            "LLM_MAIN_API_KEY=k\nLLM_MAIN_BASE_URL=https://api.deepseek.com\n",
        )
    )
    assert isinstance(c.writer, OpenAICompatClient)
    assert not any("LLM_MAIN_BASE_URL" in p for p in c.problems)
    c2 = build_clients(
        settings(tmp_path, "LLM_MAIN_PROVIDER=openai_compatible\nLLM_MAIN_MODEL=x\nLLM_MAIN_API_KEY=k\n")
    )
    assert c2.writer is None
    assert any("LLM_MAIN_BASE_URL" in p for p in c2.problems)


def test_missing_model_is_reported(tmp_path: Path) -> None:
    c = build_clients(settings(tmp_path, "LLM_MAIN_PROVIDER=anthropic\nLLM_MAIN_API_KEY=k\n"))
    assert c.writer is None
    assert any("LLM_MAIN_MODEL" in p for p in c.problems)


def test_openai_image_client(tmp_path: Path) -> None:
    c = build_clients(
        settings(tmp_path, "IMAGE_PROVIDER=openai\nIMAGE_MODEL=gpt-image-2\nIMAGE_API_KEY=sk-img\n")
    )
    assert isinstance(c.image, OpenAIImageClient)


def test_image_none(tmp_path: Path) -> None:
    assert build_clients(settings(tmp_path, "IMAGE_PROVIDER=none\n")).image is None


def test_load_prompt_fills_vars_and_keeps_json_braces() -> None:
    text = load_prompt("writer", kind="news", template="T", min_len=500, max_len=900)
    assert "{{" not in text
    assert "news" in text
    assert '{"title_short"' in text or "title_short" in text


def test_load_prompt_missing_var_raises() -> None:
    with pytest.raises(ValueError):
        load_prompt("writer", kind="news")


def test_deepseek_writer_uses_compat_client_with_default_base_url(tmp_path: Path) -> None:
    c = build_clients(
        settings(
            tmp_path, "LLM_MAIN_PROVIDER=deepseek\nLLM_MAIN_MODEL=deepseek-v4-pro\nLLM_MAIN_API_KEY=sk-ds\n"
        )
    )
    assert isinstance(c.writer, OpenAICompatClient)
    assert c.writer.provider == "deepseek"
    assert str(c.writer._client.base_url).startswith("https://api.deepseek.com")


def test_unknown_providers_reported_not_crashing(tmp_path: Path) -> None:
    c = build_clients(
        settings(
            tmp_path,
            "LLM_MAIN_PROVIDER=xyz\nLLM_MAIN_MODEL=m\nLLM_MAIN_API_KEY=k\n"
            "IMAGE_PROVIDER=foo\nIMAGE_API_KEY=k\n",
        )
    )
    assert c.writer is None and c.image is None
    assert any("LLM_MAIN_PROVIDER" in p and "xyz" in p for p in c.problems)
    assert any("IMAGE_PROVIDER" in p and "foo" in p for p in c.problems)


def test_image_key_without_provider_is_reported(tmp_path: Path) -> None:
    c = build_clients(settings(tmp_path, "IMAGE_API_KEY=sk-img\n"))
    assert c.image is None
    assert any("IMAGE_PROVIDER" in p for p in c.problems)
