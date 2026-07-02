from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)

# Anchor all default relative paths (config file, data files) to the repo root
# so the pipeline produces identical results regardless of the current working
# directory. config.py lives at <root>/family_newsletter/app/config.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


SECRET_KEYS = {
    "api_key",
    "password",
    "smtp_password",
    "resend_api_key",
    "weather_api_key",
}


class Settings(BaseSettings):
    app_env: str = "local"
    sample_mode: bool = True
    database_url: str = "sqlite:///./data/family_newsletter.db"
    config_file: str = "config.example.yaml"

    newsletter_timezone: str = "America/Los_Angeles"
    newsletter_send_time: str = "08:00"
    newsletter_enabled: bool = False

    email_provider: str = "console"
    email_from: str = "newsletter@example.com"
    email_recipients: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""

    resend_api_key: str = ""

    weather_provider: str = "sample"
    weather_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class EffectiveConfig(BaseModel):
    app: dict[str, Any] = Field(default_factory=dict)
    file_config: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)


def resolve_project_path(value: str) -> Path:
    """Resolve a path against the project root when it is relative.

    Absolute or ~-based paths are honored as-is; relative paths are anchored to
    PROJECT_ROOT instead of the current working directory so a stray CWD can't
    silently redirect us away from the real config/data files.
    """
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


# Backwards-compatible alias.
_workspace_path = resolve_project_path


def load_yaml_config(path: str) -> dict[str, Any]:
    config_path = resolve_project_path(path)
    if not config_path.exists():
        logger.warning(
            "CONFIG FILE NOT FOUND: %s (requested %r, project root %s). "
            "Falling back to defaults/sample mode -- every section will render as "
            "PLACEHOLDER/mock data. Set CONFIG_FILE or place the config at the "
            "expected location to restore live data.",
            config_path,
            path,
            PROJECT_ROOT,
        )
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in config file: {config_path}")
    return loaded


def redact_secrets(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in SECRET_KEYS:
        return "***REDACTED***" if value else ""
    if isinstance(value, dict):
        return {item_key: redact_secrets(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def get_effective_config(settings: Settings) -> EffectiveConfig:
    file_config = load_yaml_config(settings.config_file)
    env_config = settings.model_dump()
    return EffectiveConfig(
        app={
            "name": "family-newsletter",
            "sample_mode": settings.sample_mode,
            "database_url": settings.database_url,
        },
        file_config=redact_secrets(file_config),
        environment=redact_secrets(env_config),
    )


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    return Settings()


def ensure_data_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = Path(os.getcwd()) / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

