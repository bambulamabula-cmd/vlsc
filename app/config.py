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

    # Database and retention
    sqlite_path: str = "./vlsc.db"
    retention_days: int = Field(default=30, ge=1, le=3650)

    # Optional integrations
    xray_enabled: bool = False


settings = Settings()
