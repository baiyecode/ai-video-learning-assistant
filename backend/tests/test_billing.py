"""Billing foundation: the checkout entry point and the membership read.

Everything is observed at the in-process HTTP seam with a programmable fake
BillingGateway, so no test ever talks to Stripe. Membership state is asserted as
the DB-derived read model returned by ``GET /api/me/membership``.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.fakes import FAKE_CHECKOUT_URL

PASSWORD = "correct-horse"


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(client: AsyncClient, *, email: str = "learner@example.com") -> Any:
    response = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response


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
