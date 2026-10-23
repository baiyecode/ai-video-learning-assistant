from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration. Every field is overridable via ``APP_*`` env vars."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "ai-video-learning-assistant"
    app_name: str = "AI 视频学习助手"
    env: str = "development"
    debug: bool = False
    secret_key: str = "dev-only-change-me"

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    data_dir: Path = Path("./data")
    # Optional separate mount for downloaded media; defaults to ``<data_dir>/media``.
    media_root: Path | None = None
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    # Adapter configuration (consumed by the production adapters in later tickets).
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    daily_budget_usd: float = 10.0

    @property
    def media_dir(self) -> Path:
        return self.media_root if self.media_root is not None else self.data_dir / "media"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def ensure_directories(self) -> None:
        """Create runtime directories. Called once on application startup."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def load_settings() -> Settings:
    """Process-wide settings from environment / .env (used by the ASGI entrypoint)."""
    return Settings()
