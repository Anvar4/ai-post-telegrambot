"""Barcha sozlamalar `.env` dan (pydantic-settings)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PublishMode = Literal["auto", "semi_auto", "manual"]
MAIN_PROVIDERS = ("anthropic", "openai", "gemini", "deepseek", "openai_compatible")
IMAGE_PROVIDERS = ("openai", "gemini", "stability", "replicate", "fal", "none")
_PROVIDER_ALIASES = {
    "claude": "anthropic",
    "google": "gemini",
    "gpt": "openai",
    "chatgpt": "openai",
    "dall-e": "openai",
    "dalle": "openai",
    "gpt-image": "openai",
    "imagen": "gemini",
    "compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "stabilityai": "stability",
    "fal.ai": "fal",
}


def normalize_provider(value: str | None, allowed: tuple[str, ...]) -> str | None:
    """Provayder nomini tushunarli ko'rinishga keltiradi; noma'lum bo'lsa o'zgarishsiz qaytaradi."""
    if value is None or not value.strip():
        return None
    v = value.strip().lower()
    v = _PROVIDER_ALIASES.get(v, v)
    if v in allowed:
        return v
    matches = [a for a in allowed if a.startswith(v)] if len(v) >= 4 else []
    return matches[0] if len(matches) == 1 else v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: SecretStr | None = None
    channel_id: int | None = None
    channel_username: str = ""
    test_channel_id: int | None = None
    discussion_group_id: int | None = None
    test_group_id: int | None = None
    admin_ids: Annotated[list[int], NoDecode] = []
    tz: str = "Asia/Tashkent"
    publish_mode: PublishMode = "semi_auto"
    dry_run: bool = True

    # 1-kalit: yozuvchi
    llm_main_provider: str | None = None
    llm_main_model: str | None = None
    llm_main_api_key: SecretStr | None = None
    llm_main_base_url: str | None = None

    # 2-kalit: rasm
    image_provider: str | None = None
    image_model: str | None = None
    image_api_key: SecretStr | None = None
    image_size: str = "1024x1024"

    # 3-kalit: OpenAI muharrir
    openai_api_key: SecretStr | None = None
    openai_editor_model: str = "gpt-6-sol"
    openai_fast_model: str = "gpt-6-luna"

    # Ixtiyoriy manba kalitlari
    nvd_api_key: SecretStr | None = None
    github_token: SecretStr | None = None
    producthunt_token: SecretStr | None = None

    # Tizim
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    daily_budget_usd: float = 3.0
    log_level: str = "INFO"
    hash_salt: SecretStr | None = None
    model_prices_json: str | None = None
    data_dir: Path = Path("data")
    http_timeout: float = 20.0
    ai_timeout: float = 120.0

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [int(part) for part in value.replace(";", ",").split(",") if part.strip()]
        if isinstance(value, int):
            return [value]
        return value

    @field_validator("llm_main_provider", mode="before")
    @classmethod
    def _main_provider(cls, value: Any) -> Any:
        return normalize_provider(value, MAIN_PROVIDERS) if isinstance(value, str) else value

    @field_validator("image_provider", mode="before")
    @classmethod
    def _image_provider(cls, value: Any) -> Any:
        return normalize_provider(value, IMAGE_PROVIDERS) if isinstance(value, str) else value

    @field_validator("channel_username", mode="before")
    @classmethod
    def _at_username(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if value.startswith("https://t.me/"):
                value = value.removeprefix("https://t.me/")
            return value if value.startswith("@") else f"@{value}"
        return value

    # --- hosilaviy qiymatlar ---

    @property
    def target_chat_id(self) -> int | None:
        """Postlar boradigan chat. DRY_RUN da hech qachon haqiqiy kanal emas."""
        if self.dry_run:
            return self.test_channel_id
        return self.channel_id

    @property
    def sync_database_url(self) -> str:
        """APScheduler SQLAlchemyJobStore va Alembic uchun sinxron URL."""
        url = self.database_url
        url = url.replace("+aiosqlite", "")
        url = url.replace("+asyncpg", "+psycopg")
        return url

    @property
    def data_path(self) -> Path:
        return self.data_dir

    @property
    def model_prices(self) -> dict[str, dict[str, float]]:
        if not self.model_prices_json:
            return {}
        try:
            data = json.loads(self.model_prices_json)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    def secret_values(self) -> list[str]:
        """Logda maskalanadigan barcha sir qiymatlari."""
        secrets = [
            self.telegram_bot_token,
            self.llm_main_api_key,
            self.image_api_key,
            self.openai_api_key,
            self.nvd_api_key,
            self.github_token,
            self.producthunt_token,
            self.hash_salt,
        ]
        return [s.get_secret_value() for s in secrets if s and s.get_secret_value()]


def env_file_warnings(path: Path | str = ".env") -> list[str]:
    """.env dagi takrorlangan kalitlar (oxirgisi ustun keladi — ko'pincha bo'sh qiymat kalitni yo'qotadi)."""
    p = Path(path)
    if not p.is_file():
        return []
    seen: dict[str, list[tuple[int, bool]]] = {}
    for n, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip()
        seen.setdefault(key.strip(), []).append((n, bool(value)))
    warnings = []
    for key, entries in seen.items():
        if len(entries) < 2:
            continue
        rows = ", ".join(str(n) for n, _ in entries)
        if entries[-1][1] is False and any(filled for _, filled in entries[:-1]):
            warnings.append(
                f".env: {key} {rows}-qatorlarda takrorlangan, oxirgisi boʻsh — qiymat yoʻqoladi. "
                "Boʻsh qatorni oʻchiring."
            )
        else:
            warnings.append(f".env: {key} {rows}-qatorlarda takrorlangan — oxirgisi ishlatiladi.")
    return warnings


def load_settings(env_file: Path | str | None = ".env") -> tuple[Settings | None, str | None]:
    """Sozlamalarni yuklaydi; xato bo'lsa tushunarli matn qaytaradi (traceback o'rniga)."""
    from pydantic import ValidationError

    from app.utils.security import mask_secrets

    try:
        return Settings(_env_file=env_file), None  # type: ignore[call-arg]
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            field = ".".join(str(x) for x in err.get("loc", ())).upper()
            lines.append(f"• {field}: {err.get('msg')} (qiymat: {mask_secrets(repr(err.get('input')))[:60]})")
        return None, ".env da notoʻgʻri qiymatlar:\n" + "\n".join(lines)


@lru_cache
def get_settings() -> Settings:
    return Settings()
