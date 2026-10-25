from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that must never reach a production deployment.
_DEV_SECRETS = {
    "",
    "dev-only-change-me",
    "change-me",
    "changeme",
    "change-me-in-production",
    "secret",
}


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
    rate_limit_report_per_hour: int = 5
    # Email-verification resend (ticket #22): per Account, not per IP, since the
    # endpoint requires a login. Guards against the product being used as a mail relay.
    rate_limit_verification_request_per_hour: int = 3
    # Verification-link confirmations (story 26): unauthenticated, so keyed per
    # client address; bounds token-guessing bursts without touching mail sending.
    rate_limit_verification_confirm_per_hour: int = 10

    # Deterministic in-process adapters (seeded demo video + canned Summarizer) for
    # the Playwright golden path. Never enable this in production.
    fake_adapters: bool = False

    # Subscription billing (ticket P2-01). Development may leave the Stripe
    # credentials unset; billing requests then answer 503 instead of crashing.
    # Production refuses to start without all three (ticket P2-10, below).
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    # Display-only monthly price shown by the pricing UI; billing maths lives in Stripe.
    # If this drifts from the real ``stripe_price_id`` configuration the payment
    # provider's checkout page wins: 实际扣款以支付方配置为准 (frontend copy and
    # ``frontend/src/lib/billing.ts`` say the same). Keep the two in sync when repricing.
    subscription_monthly_usd: float = 4.99

    # Feature switches (ticket #23). Douyin parsing ships behind this switch so it can
    # be opened and rolled back per deployment without a code change.
    douyin_enabled: bool = False

    # Email verification (ticket #21): lifetime of the one-time verification token
    # (kept short on purpose; 24h is the cap) and the product page the email links back to.
    email_verification_token_ttl_hours: int = 24
    frontend_base_url: str = "http://localhost:5173"

    # SMTP email delivery (thin wrapper; credential enforcement is production hardening).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from: str = ""

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

    def validate_production_secrets(self) -> None:
        """Refuse to start production with missing or development secrets.

        File URLs are signed with ``secret_key`` and access tokens with
        ``jwt_secret`` (falling back to ``secret_key``); shipping the development
        defaults would let anyone forge either. From ticket P2-10 the same guard
        also refuses a half-set payment (Stripe) or outbound email (SMTP)
        configuration: both would only fail later, as silent 503s for users.
        """
        if not self.is_production:
            return
        if self.secret_key.strip().lower() in _DEV_SECRETS:
            raise RuntimeError(
                "APP_SECRET_KEY must be set to a strong, non-default value when "
                "APP_ENV=production"
            )
        if self.jwt_secret.strip().lower() in _DEV_SECRETS and self.jwt_secret.strip():
            raise RuntimeError(
                "APP_JWT_SECRET must be empty (fallback to APP_SECRET_KEY) or a strong, "
                "non-default value when APP_ENV=production"
            )
        if self.fake_adapters:
            raise RuntimeError("APP_FAKE_ADAPTERS is a test-only switch and must be off in production")
        # Payment (ticket P2-10): a production deployment must never run with a half-set
        # Stripe configuration; users would see 503s on every upgrade attempt.
        for field, name in (
            (self.stripe_api_key, "APP_STRIPE_API_KEY"),
            (self.stripe_webhook_secret, "APP_STRIPE_WEBHOOK_SECRET"),
            (self.stripe_price_id, "APP_STRIPE_PRICE_ID"),
        ):
            if not field.strip():
                raise RuntimeError(f"{name} must be set to the real Stripe value when APP_ENV=production")
        # Outbound email (ticket P2-10): verification links are worthless if the sender
        # would silently fail closed with a 503. Host + from are the minimum the SMTP
        # adapter needs (username/password stay optional for unauthenticated relays).
        if not self.smtp_host.strip():
            raise RuntimeError(
                "APP_SMTP_HOST must be set to the outbound mail server when APP_ENV=production "
                "(development may leave it empty and use the fake sender)"
            )
        if not self.smtp_from.strip():
            raise RuntimeError(
                "APP_SMTP_FROM must be set to the verified sender address when APP_ENV=production "
                "(development may leave it empty and use the fake sender)"
            )


@lru_cache
def load_settings() -> Settings:
    """Process-wide settings from environment / .env (used by the ASGI entrypoint)."""
    return Settings()
