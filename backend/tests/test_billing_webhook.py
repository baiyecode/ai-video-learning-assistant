"""Webhook state machine: payment success activates membership, idempotent and ordered.

Everything is observed at the in-process HTTP seam: raw event POSTs to
``/api/billing/webhook`` (no auth, Stripe-style signature header), the derived read
model at ``GET /api/me/membership``, the ``billing_events`` audit rows and the JSON
log lines. Verification and decoding live behind the BillingGateway port, so no test
talks to Stripe and no port listener is opened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from httpx import AsyncClient

from tests.fakes import checkout_completed_body, sign_webhook

PASSWORD = "correct-horse"
EVENT_CREATED = "2026-01-15T09:00:00+00:00"
PERIOD_END = "2026-02-14T09:00:00+00:00"


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(client: AsyncClient, *, email: str) -> Any:
    response = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _post_event(client: AsyncClient, body: bytes) -> Any:
    return await client.post(
        "/api/billing/webhook",
        content=body,
        headers={"stripe-signature": sign_webhook(body)},
    )


async def test_checkout_completed_event_activates_membership(client: AsyncClient) -> None:
    """AC1: a verified checkout-completed event makes the Account VIP with a period end."""
    response = await register(client, email="paid@example.com")
    account_id = response.json()["account"]["id"]

    body = checkout_completed_body(
        "evt_checkout_1",
        account_id,
        created=_dt(EVENT_CREATED),
        period_end=_dt(PERIOD_END),
    )
    webhook = await _post_event(client, body)

    assert webhook.status_code == 200, webhook.text

    membership = await client.get("/api/me/membership", headers=bearer(response))
    assert membership.status_code == 200, membership.text
    assert membership.json() == {
        "status": "active",
        "period_end": PERIOD_END,
        "portal_url": None,
    }
