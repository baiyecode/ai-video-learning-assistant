"""Billing foundation: the checkout entry point and the membership read.

Everything is observed at the in-process HTTP seam with a programmable fake
BillingGateway, so no test ever talks to Stripe. Membership state is asserted as
the DB-derived read model returned by ``GET /api/me/membership``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from app.modules.billing.models import Subscription
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from tests.fakes import FAKE_CHECKOUT_URL

PASSWORD = "correct-horse"


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(client: AsyncClient, *, email: str = "learner@example.com") -> Any:
    response = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response


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
    assert response.json() == {"status": "free", "period_end": None, "portal_url": None}


async def test_membership_reports_a_recorded_subscription(client: AsyncClient, app: FastAPI) -> None:
    response = await register(client, email="vip@example.com")
    await seed_subscription(app, response.json()["account"]["id"])

    membership = await client.get("/api/me/membership", headers=bearer(response))

    assert membership.status_code == 200, membership.text
    assert membership.json() == {
        "status": "active",
        "period_end": "2026-02-14T08:00:00+00:00",
        "portal_url": None,
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
