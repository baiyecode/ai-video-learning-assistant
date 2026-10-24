"""Production configuration guards: development secrets and test-only switches."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings


def _production(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "env": "production",
        "secret_key": "a-strong-production-secret",
        "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        "data_dir": tmp_path / "data",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "secret",
    ["", "dev-only-change-me", "change-me", "changeme", "secret"],
)
def test_production_rejects_missing_or_development_secret(tmp_path: Path, secret: str) -> None:
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        _production(tmp_path, secret_key=secret).validate_production_secrets()


def test_production_rejects_a_development_jwt_secret(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="APP_JWT_SECRET"):
        _production(tmp_path, jwt_secret="change-me").validate_production_secrets()


def test_production_rejects_the_fake_adapter_switch(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="APP_FAKE_ADAPTERS"):
        _production(tmp_path, fake_adapters=True).validate_production_secrets()


def test_production_accepts_strong_secrets_and_empty_jwt_fallback(tmp_path: Path) -> None:
    _production(tmp_path).validate_production_secrets()


def test_development_keeps_its_convenience_defaults(tmp_path: Path) -> None:
    settings = _production(tmp_path, env="test", secret_key="dev-only-change-me")
    settings.validate_production_secrets()


def test_subscription_defaults_follow_the_app_prefix_convention() -> None:
    settings = Settings(_env_file=None, env="test", secret_key="test-only-secret")

    assert settings.stripe_api_key == ""
    assert settings.stripe_webhook_secret == ""
    assert settings.stripe_price_id == ""
    assert settings.subscription_monthly_usd == 4.99


def test_stripe_settings_read_app_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_STRIPE_API_KEY", "sk_test_123")
    monkeypatch.setenv("APP_STRIPE_WEBHOOK_SECRET", "whsec_123")
    monkeypatch.setenv("APP_STRIPE_PRICE_ID", "price_monthly_1")
    monkeypatch.setenv("APP_SUBSCRIPTION_MONTHLY_USD", "9.99")

    settings = Settings(_env_file=None, env="test", secret_key="test-only-secret")

    assert settings.stripe_api_key == "sk_test_123"
    assert settings.stripe_webhook_secret == "whsec_123"
    assert settings.stripe_price_id == "price_monthly_1"
    assert settings.subscription_monthly_usd == 9.99
