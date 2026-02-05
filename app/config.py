from collections.abc import Mapping

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="VLSC_", env_file=".env", extra="ignore")

    app_name: str = "VLSC"
    debug: bool = False

    # Runtime controls
    check_timeout_seconds: int = Field(default=10, ge=1, le=300)
    request_timeout_seconds: int = Field(default=20, ge=1, le=600)
    concurrency_limit: int = Field(default=20, ge=1, le=500)
    import_file_max_bytes: int = Field(default=1024 * 1024, ge=1)

    # Database and retention
    sqlite_path: str = "./vlsc.db"
    retention_days: int = Field(default=30, ge=1, le=3650)

    # Optional integrations
    xray_enabled: bool = False


settings = Settings()


def settings_defaults() -> dict[str, object]:
    return {name: field.default for name, field in Settings.model_fields.items()}


def apply_runtime_settings_overrides(overrides: Mapping[str, object]) -> None:
    for name, raw_value in overrides.items():
        if name not in Settings.model_fields:
            continue
        setattr(settings, name, raw_value)
