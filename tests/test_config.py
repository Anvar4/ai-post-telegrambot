from pathlib import Path

import pytest

from app.config import Settings


def load(tmp_path: Path, text: str) -> Settings:
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    return Settings(_env_file=env)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CHANNEL_ID", "TEST_CHANNEL_ID", "ADMIN_IDS", "DRY_RUN", "DATABASE_URL", "TZ"):
        monkeypatch.delenv(key, raising=False)


def test_empty_values_become_none(tmp_path: Path) -> None:
    s = load(tmp_path, "CHANNEL_ID=\nTEST_CHANNEL_ID=-1001\nLLM_MAIN_PROVIDER=\n")
    assert s.channel_id is None
    assert s.test_channel_id == -1001
    assert s.llm_main_provider is None


def test_admin_ids_csv(tmp_path: Path) -> None:
    s = load(tmp_path, "ADMIN_IDS=1, 2\n")
    assert s.admin_ids == [1, 2]
    assert s.is_admin(2)
    assert not s.is_admin(3)


def test_admin_ids_empty_is_empty_list(tmp_path: Path) -> None:
    s = load(tmp_path, "ADMIN_IDS=\n")
    assert s.admin_ids == []


def test_target_chat_dry_run_never_real_channel(tmp_path: Path) -> None:
    s = load(tmp_path, "DRY_RUN=true\nCHANNEL_ID=-1002\nTEST_CHANNEL_ID=-1001\n")
    assert s.target_chat_id == -1001
    s2 = load(tmp_path, "DRY_RUN=true\nCHANNEL_ID=-1002\n")
    assert s2.target_chat_id is None


def test_target_chat_live(tmp_path: Path) -> None:
    s = load(tmp_path, "DRY_RUN=false\nCHANNEL_ID=-1002\nTEST_CHANNEL_ID=-1001\n")
    assert s.target_chat_id == -1002


def test_sync_url(tmp_path: Path) -> None:
    s = load(tmp_path, "DATABASE_URL=sqlite+aiosqlite:///data/bot.db\n")
    assert s.sync_database_url == "sqlite:///data/bot.db"
    s2 = load(tmp_path, "DATABASE_URL=postgresql+asyncpg://u:p@h/db\n")
    assert s2.sync_database_url == "postgresql+psycopg://u:p@h/db"


def test_defaults(tmp_path: Path) -> None:
    s = load(tmp_path, "")
    assert s.publish_mode == "semi_auto"
    assert s.dry_run is True
    assert s.openai_editor_model == "gpt-6-sol"
    assert s.openai_fast_model == "gpt-6-luna"
    assert s.tz == "Asia/Tashkent"
    assert s.daily_budget_usd == 3.0


def test_env_example_has_no_secret_values() -> None:
    root = Path(__file__).resolve().parents[1]
    secret_keys = ("TOKEN", "API_KEY", "SALT")
    for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        if any(s in key for s in secret_keys):
            assert value.strip() == "", f".env.example da {key} qiymati bor — sirlar faqat .env da"


def test_channel_username_normalized(tmp_path: Path) -> None:
    s = load(tmp_path, "CHANNEL_USERNAME=it_dunyosi\n")
    assert s.channel_username == "@it_dunyosi"
