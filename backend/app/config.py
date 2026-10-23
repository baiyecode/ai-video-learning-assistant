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

    # Authentication. ``jwt_secret`` falls back to ``secret_key`` when unset.
    jwt_secret: str = ""
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    refresh_cookie_name: str = "refresh_token"
    # ``None`` means: Secure in production, relaxed for local development/tests.
    auth_cookie_secure: bool | None = None

    # Download resource boundaries (see docs/adr/0001-single-vps-sqlite.md).
    download_global_concurrency: int = 5
    download_account_concurrency: int = 2
    download_visitor_concurrency: int = 1
    download_visitor_hourly_limit: int = 5
    download_max_duration_seconds: int = 2 * 60 * 60
    download_max_file_size_bytes: int = 2 * 1024**3
    # How often the in-process cleanup task looks for expired files. Zero disables it.
    download_cleanup_interval_seconds: float = 60.0

    # Adapter configuration (consumed by the production adapters in later tickets).
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    daily_budget_usd: float = 10.0
    # Conservative per-call estimate used to gate and record each Summarizer call.
    analysis_cost_per_call_usd: float = 0.01

    # Analysis (ticket #8): free Quota per Account per Asia/Shanghai day and the
    # end-to-end generation timeout. #12 adds rate limits and budget policy.
    analysis_daily_quota: int = 3
    analysis_timeout_seconds: float = 120.0
    # Long-Subtitle chunking (ticket #9): per-chunk character budget (splits only at
    # cue boundaries) and the total input budget. Beyond it chunks distributed across
    # the timeline are kept and the Analysis is flagged ``truncated``.
    analysis_chunk_chars: int = 6000
    analysis_max_input_chars: int = 120_000

    # Rate limits (ticket #12). Sliding windows, in-memory per process; a value of 0
    # disables that scope. Scopes key on the client IP except Analysis (per Account).
    rate_limit_resolve_per_minute: int = 10
    rate_limit_download_per_minute: int = 3
    rate_limit_login_per_15_minutes: int = 10
    rate_limit_register_per_hour: int = 5
    rate_limit_analysis_seconds: float = 10.0

    @property
    def media_dir(self) -> Path:
        return self.media_root if self.media_root is not None else self.data_dir / "media"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def jwt_signing_key(self) -> str:
        """HMAC key for access tokens; a dedicated JWT secret wins over the app secret."""
        return self.jwt_secret or self.secret_key

    @property
    def refresh_cookie_secure(self) -> bool:
        """HttpOnly refresh cookie is Secure unless explicitly relaxed in development."""
        if self.auth_cookie_secure is None:
            return self.is_production
        return self.auth_cookie_secure

    def ensure_directories(self) -> None:
        """Create runtime directories. Called once on application startup."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def load_settings() -> Settings:
    """Process-wide settings from environment / .env (used by the ASGI entrypoint)."""
    return Settings()
