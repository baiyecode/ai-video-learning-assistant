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
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

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


async def test_subscription_updated_backfills_the_period_end_the_checkout_omitted(
    client: AsyncClient
) -> None:
    """P2-02 leftover: a real checkout object may lack the period end; a later
    ``customer.subscription.updated`` (status still active, i.e. cancelled-at-period-end
    semantics) writes it in and VIP survives until then."""
    response = await register(client, email="periodend@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    checkout = checkout_completed_body("evt_lc_no_period", account_id, created=_dt(CHECKOUT_CREATED))
    assert (await _post_event(client, checkout)).status_code == 200
    assert (await _membership(client, auth))["period_end"] is None

    updated = lifecycle_event_body(
        "evt_lc_update_1",
        "customer.subscription.updated",
        _dt("2026-01-15T09:30:00+00:00"),
        account_id=account_id,
        period_end=_dt(PERIOD_END),
        subscription_status="active",
    )
    assert (await _post_event(client, updated)).status_code == 200

    assert await _membership(client, auth) == {
        "status": "active",
        "period_end": PERIOD_END,
        "portal_url": None,
        "is_vip": True,
    }


async def test_subscription_updated_trialing_maps_to_trial_ending_and_keeps_vip(
    client: AsyncClient, app: FastAPI
) -> None:
    """A subscription object in ``trialing`` lands on trial_ending: still VIP (AC3)."""
    response = await register(client, email="trialing@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    updated = lifecycle_event_body(
        "evt_lc_trial",
        "customer.subscription.updated",
        _dt("2026-01-15T10:00:00+00:00"),
        account_id=account_id,
        subscription_status="trialing",
    )
    assert (await _post_event(client, updated)).status_code == 200

    membership = await _membership(client, auth)
    assert membership["status"] == "trial_ending"
    assert membership["is_vip"] is True


async def test_subscription_updated_with_an_unrecognized_status_never_moves_state(
    client: AsyncClient, app: FastAPI
) -> None:
    """Unknown payload statuses are never guessed: audit row, no transition."""
    response = await register(client, email="weird@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    updated = lifecycle_event_body(
        "evt_lc_weird",
        "customer.subscription.updated",
        _dt("2026-01-15T10:00:00+00:00"),
        account_id=account_id,
        subscription_status="incomplete_expired",
    )
    assert (await _post_event(client, updated)).status_code == 200

    assert (await _membership(client, auth))["status"] == "active"
    rows = await _audit_rows(app, "evt_lc_weird")
    assert [row.applied for row in rows] == [False]


async def _audit_rows(app: FastAPI, event_id: str) -> list:
    from app.modules.billing.models import BillingEvent

    async with app.state.sessionmaker() as session:
        return list(
            (await session.scalars(select(BillingEvent).where(BillingEvent.event_id == event_id))).all()
        )


async def test_event_naming_only_the_stripe_ids_moves_state_and_lands_on_the_right_audit_trail(
    client: AsyncClient, app: FastAPI
) -> None:
    """Real invoice events carry only Stripe ids: the subscription id resolves the owner."""
    response = await register(client, email="stripeonly@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    failed = lifecycle_event_body(
        "evt_no_account", "invoice.payment_failed", _dt("2026-01-15T10:00:00+00:00")
    )
    assert (await _post_event(client, failed)).status_code == 200

    assert (await _membership(client, auth))["status"] == "past_due"
    rows = await _audit_rows(app, "evt_no_account")
    assert [(row.account_id, row.applied) for row in rows] == [(account_id, True)]


async def test_late_lifecycle_event_older_than_the_newest_is_audit_only(
    client: AsyncClient, app: FastAPI
) -> None:
    """Out-of-order still wins nobody: the stale failure cannot undo the newer success."""
    response = await register(client, email="latefail@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    succeeded = lifecycle_event_body(
        "evt_new_success",
        "invoice.payment_succeeded",
        _dt("2026-01-16T10:00:00+00:00"),
        account_id=account_id,
    )
    assert (await _post_event(client, succeeded)).status_code == 200

    late_failure = lifecycle_event_body(
        "evt_late_failure",
        "invoice.payment_failed",
        _dt("2026-01-15T12:00:00+00:00"),
        account_id=account_id,
    )
    assert (await _post_event(client, late_failure)).status_code == 200

    membership = await _membership(client, auth)
    assert membership["status"] == "active"
    assert membership["is_vip"] is True
    rows = await _audit_rows(app, "evt_late_failure")
    assert [row.applied for row in rows] == [False]


async def test_lifecycle_event_for_an_unknown_subscription_changes_nothing(
    client: AsyncClient, app: FastAPI
) -> None:
    """An event whose subscription id matches no record is acknowledged, audited, inert."""
    response = await register(client, email="orphan@example.com")
    auth = bearer(response)

    orphan = lifecycle_event_body(
        "evt_orphan",
        "customer.subscription.deleted",
        _dt("2026-01-15T10:00:00+00:00"),
        subscription_id="sub_never_seen",
    )
    assert (await _post_event(client, orphan)).status_code == 200

    assert (await _membership(client, auth))["status"] == "free"
    rows = await _audit_rows(app, "evt_orphan")
    assert [(row.account_id, row.applied) for row in rows] == [(None, False)]
