"""Subscription lifecycle beyond first payment: failures, recovery, cancellations.

Everything is observed at the in-process HTTP seam: lifecycle events are POSTed to
``/api/billing/webhook`` through the fake BillingGateway exactly like Stripe delivers
them (signature header + Stripe-style body), and the derived truth is read back from
``GET /api/me/membership``. State only ever moves on events - no local guessing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient

from tests.auth_flows import login as auth_login
from tests.auth_flows import register as auth_register
from tests.fakes import checkout_completed_body, lifecycle_event_body, sign_webhook

PASSWORD = "correct-horse"
CHECKOUT_CREATED = "2026-01-15T09:00:00+00:00"
PERIOD_END = "2026-02-14T09:00:00+00:00"


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(client: AsyncClient, *, email: str) -> Any:
    await auth_register(client, email=email, password=PASSWORD)
    return await auth_login(client, email=email, password=PASSWORD)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _post_event(client: AsyncClient, body: bytes) -> Any:
    return await client.post(
        "/api/billing/webhook",
        content=body,
        headers={"stripe-signature": sign_webhook(body)},
    )


async def _activate(client: AsyncClient, account_id: str) -> None:
    """Put the Account into the Active state the way production does: a checkout event."""
    body = checkout_completed_body(
        "evt_lc_checkout", account_id, created=_dt(CHECKOUT_CREATED), period_end=_dt(PERIOD_END)
    )
    response = await _post_event(client, body)
    assert response.status_code == 200, response.text


async def _membership(client: AsyncClient, auth: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/api/me/membership", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("event_type", "expected_status"),
    [
        ("invoice.payment_failed", "past_due"),
        ("customer.subscription.deleted", "canceled"),
    ],
)
async def test_lifecycle_events_advance_the_membership_status(
    client: AsyncClient, event_type: str, expected_status: str
) -> None:
    """AC1/AC2: a later verified event moves the recorded status; VIP rides on it."""
    response = await register(client, email=f"{event_type}@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    body = lifecycle_event_body(
        f"evt_{event_type}_1",
        event_type,
        _dt("2026-01-15T10:00:00+00:00"),
        account_id=account_id,
    )
    webhook = await _post_event(client, body)

    assert webhook.status_code == 200, webhook.text
    assert await _membership(client, auth) == {
        "status": expected_status,
        "period_end": PERIOD_END,
        "portal_url": None,
        "is_vip": False,
    }


async def test_payment_succeeded_restores_an_active_membership(client: AsyncClient) -> None:
    """AC1: after a failed charge, a successful invoice brings VIP back."""
    response = await register(client, email="recovered@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    failed = lifecycle_event_body(
        "evt_fail", "invoice.payment_failed", _dt("2026-01-15T10:00:00+00:00"), account_id=account_id
    )
    assert (await _post_event(client, failed)).status_code == 200
    succeeded = lifecycle_event_body(
        "evt_success",
        "invoice.payment_succeeded",
        _dt("2026-01-16T10:00:00+00:00"),
        account_id=account_id,
        period_end=_dt("2026-03-14T10:00:00+00:00"),
    )
    assert (await _post_event(client, succeeded)).status_code == 200

    assert await _membership(client, auth) == {
        "status": "active",
        "period_end": "2026-03-14T10:00:00+00:00",
        "portal_url": None,
        "is_vip": True,
    }
