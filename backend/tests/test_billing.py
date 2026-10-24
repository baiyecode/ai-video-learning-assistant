"""Billing foundation: the checkout entry point and the membership read.

Everything is observed at the in-process HTTP seam with a programmable fake
BillingGateway, so no test ever talks to Stripe. Membership state is asserted as
the DB-derived read model returned by ``GET /api/me/membership``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.modules.billing.models import Subscription
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from tests.auth_flows import login as auth_login
from tests.auth_flows import register as auth_register
from tests.fakes import FAKE_CHECKOUT_URL

PASSWORD = "correct-horse"


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(client: AsyncClient, *, email: str = "learner@example.com") -> Any:
    """Register then log in: billing reads the Session, not the verification state."""
    await auth_register(client, email=email, password=PASSWORD)
    return await auth_login(client, email=email, password=PASSWORD)


async def seed_subscription(
    app: FastAPI,
    account_id: str,
    *,
    status: str = "active",
    stripe_subscription_id: str = "sub_fake_1",
    current_period_end: datetime | None = datetime(2026, 2, 14, 8, 0, tzinfo=UTC),
) -> None:
    """Insert a subscription row the way the webhook handler eventually will."""
    async with app.state.sessionmaker() as session:
        session.add(
            Subscription(
                account_id=account_id,
                stripe_customer_id="cus_fake_1",
                stripe_subscription_id=stripe_subscription_id,
                status=status,
                current_period_end=current_period_end,
                price_id="price_fake_monthly",
            )
        )
        await session.commit()


async def test_anonymous_cannot_open_a_checkout(client: AsyncClient) -> None:
    response = await client.post("/api/billing/checkout")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "auth_required"


async def test_logged_in_account_receives_the_gateway_checkout_url(client: AsyncClient) -> None:
    auth = bearer(await register(client))

    response = await client.post("/api/billing/checkout", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json() == {"url": FAKE_CHECKOUT_URL}


async def test_membership_is_free_before_any_subscription(client: AsyncClient) -> None:
    auth = bearer(await register(client))

    response = await client.get("/api/me/membership", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "free", "period_end": None, "portal_url": None, "is_vip": False}


async def test_membership_reports_a_recorded_subscription(client: AsyncClient, app: FastAPI) -> None:
    response = await register(client, email="vip@example.com")
    await seed_subscription(app, response.json()["account"]["id"])

    membership = await client.get("/api/me/membership", headers=bearer(response))

    assert membership.status_code == 200, membership.text
    assert membership.json() == {
        "status": "active",
        "period_end": "2026-02-14T08:00:00+00:00",
        "portal_url": None,
        "is_vip": True,
    }


async def test_anonymous_cannot_read_membership(client: AsyncClient) -> None:
    response = await client.get("/api/me/membership")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "auth_required"


@pytest.mark.parametrize("status", ["active", "trial_ending", "past_due", "canceled"])
async def test_membership_surfaces_every_lifecycle_status(
    client: AsyncClient, app: FastAPI, status: str
) -> None:
    response = await register(client, email=f"{status}@example.com")
    await seed_subscription(app, response.json()["account"]["id"], status=status)

    membership = await client.get("/api/me/membership", headers=bearer(response))

    assert membership.status_code == 200, membership.text
    assert membership.json()["status"] == status


async def test_stripe_subscription_id_is_the_idempotency_key(
    client: AsyncClient, app: FastAPI
) -> None:
    first = (await register(client, email="one@example.com")).json()["account"]["id"]
    second = (await register(client, email="two@example.com")).json()["account"]["id"]
    await seed_subscription(app, first, stripe_subscription_id="sub_shared")

    with pytest.raises(IntegrityError):
        await seed_subscription(app, second, stripe_subscription_id="sub_shared")


async def test_one_subscription_per_account(client: AsyncClient, app: FastAPI) -> None:
    account_id = (await register(client, email="solo@example.com")).json()["account"]["id"]
    await seed_subscription(app, account_id, stripe_subscription_id="sub_first")

    with pytest.raises(IntegrityError):
        await seed_subscription(app, account_id, stripe_subscription_id="sub_second")


def _bare_settings(**overrides: object):
    from app.config import Settings

    values: dict[str, object] = {
        "_env_file": None,
        "env": "test",
        "secret_key": "test-only-secret",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


async def test_unconfigured_stripe_gateway_constructs_but_answers_503() -> None:
    """Development without Stripe keys: no crash at wiring, an understood 503 per request."""
    from app.adapters.stripe_billing import StripeBillingGateway
    from app.errors import AppError

    gateway = StripeBillingGateway(_bare_settings())

    with pytest.raises(AppError) as raised:
        await gateway.create_checkout(
            account_id="acct_1",
            email="learner@example.com",
            price_id="",
            success_url="http://testserver/?checkout=success",
            cancel_url="http://testserver/?checkout=cancelled",
        )

    assert raised.value.status == 503
    assert raised.value.code == "service_unavailable"
    assert "订阅" in raised.value.message


async def test_configured_stripe_gateway_reaches_the_sdk_layer(monkeypatch) -> None:
    """With keys present the guard passes and the (uninstalled or unreachable) SDK fails as 503."""
    import sys

    from app.adapters import stripe_billing
    from app.errors import AppError

    monkeypatch.setitem(sys.modules, "stripe", None)  # force the import path to blow up
    gateway = stripe_billing.StripeBillingGateway(
        _bare_settings(stripe_api_key="sk_test_real", stripe_price_id="price_real")
    )

    with pytest.raises(AppError) as raised:
        await gateway.create_checkout(
            account_id="acct_1",
            email=None,
            price_id="price_real",
            success_url="http://testserver/?checkout=success",
            cancel_url="http://testserver/?checkout=cancelled",
        )

    assert raised.value.status == 503
    assert raised.value.code == "service_unavailable"


async def test_checkout_endpoint_answers_503_on_production_wiring_without_keys(
    tmp_path: Path,
) -> None:
    """The whole production adapter path: the app boots and the endpoint explains itself."""
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        env="test",
        secret_key="test-only-secret",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        data_dir=tmp_path / "data",
        log_level="WARNING",
    )
    production_app = create_app(settings=settings)
    transport = httpx.ASGITransport(app=production_app, raise_app_exceptions=False)

    async with LifespanManager(production_app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            authed = await register(http_client, email="upgrade@example.com")
            response = await http_client.post("/api/billing/checkout", headers=bearer(authed))

    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "service_unavailable"
    assert "订阅" in error["message"]
