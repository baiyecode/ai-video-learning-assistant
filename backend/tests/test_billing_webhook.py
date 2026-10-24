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

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

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


async def _audit_rows(app: FastAPI, event_id: str) -> list:
    from app.modules.billing.models import BillingEvent

    async with app.state.sessionmaker() as session:
        return list(
            (
                await session.scalars(select(BillingEvent).where(BillingEvent.event_id == event_id))
            ).all()
        )


async def test_replayed_event_id_applies_once_and_still_answers_2xx(
    client: AsyncClient, app: FastAPI
) -> None:
    """AC2: Stripe redelivery of one event_id is idempotent yet keeps answering 2xx.

    The second delivery carries the SAME event id but a tampered period end: if the
    replay ever touched state the membership would visibly shift.
    """
    response = await register(client, email="replay@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)

    first = checkout_completed_body(
        "evt_replay_1", account_id, created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )
    assert (await _post_event(client, first)).status_code == 200

    second = checkout_completed_body(
        "evt_replay_1",
        account_id,
        created=_dt(EVENT_CREATED),
        period_end=_dt("2026-03-14T09:00:00+00:00"),
        subscription_id="sub_tampered",
    )
    again = await _post_event(client, second)

    assert again.status_code == 200, again.text
    membership = await client.get("/api/me/membership", headers=auth)
    assert membership.json()["period_end"] == PERIOD_END
    assert membership.json()["status"] == "active"

    rows = await _audit_rows(app, "evt_replay_1")
    assert len(rows) == 1, "one event_id must leave exactly one audit row"


async def test_event_older_than_the_latest_record_never_rolls_state_back(
    client: AsyncClient, app: FastAPI
) -> None:
    """AC3: an out-of-order delivery older than the newest local event is audit-only."""
    response = await register(client, email="ordered@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)

    newest = checkout_completed_body(
        "evt_new",
        account_id,
        created=_dt("2026-01-15T10:00:00+00:00"),
        period_end=_dt(PERIOD_END),
    )
    assert (await _post_event(client, newest)).status_code == 200

    older = checkout_completed_body(
        "evt_old",
        account_id,
        created=_dt("2026-01-15T09:00:00+00:00"),
        period_end=_dt("2026-01-30T09:00:00+00:00"),
        subscription_id="sub_older",
    )
    replay = await _post_event(client, older)

    assert replay.status_code == 200, replay.text
    membership = await client.get("/api/me/membership", headers=auth)
    assert membership.json()["period_end"] == PERIOD_END
    assert membership.json()["status"] == "active"

    old_rows = await _audit_rows(app, "evt_old")
    assert [row.applied for row in old_rows] == [False], "stale events keep the audit trail"
    new_rows = await _audit_rows(app, "evt_new")
    assert [row.applied for row in new_rows] == [True]
