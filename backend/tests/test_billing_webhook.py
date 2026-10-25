"""Webhook state machine: payment success activates membership, idempotent and ordered.

Everything is observed at the in-process HTTP seam: raw event POSTs to
``/api/billing/webhook`` (no auth, Stripe-style signature header), the derived read
model at ``GET /api/me/membership``, the ``billing_events`` audit rows and the JSON
log lines. Verification and decoding live behind the BillingGateway port, so no test
talks to Stripe and no port listener is opened.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from app.container import Adapters
from app.errors import AppError, ErrorCode
from app.logging_setup import JsonFormatter
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from tests.auth_flows import login as auth_login
from tests.auth_flows import register as auth_register
from tests.fakes import checkout_completed_body, sign_webhook, webhook_event_body

PASSWORD = "correct-horse"
EVENT_CREATED = "2026-01-15T09:00:00+00:00"
PERIOD_END = "2026-02-14T09:00:00+00:00"


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(client: AsyncClient, *, email: str) -> Any:
    """Register then log in: webhook reads need the Account id and a Session, not verification."""
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
        "cancel_at_period_end": False,
        "is_vip": True,
        "portal_url": "/api/billing/portal",
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


async def test_unknown_event_type_is_recorded_but_never_moves_state(
    client: AsyncClient, app: FastAPI
) -> None:
    """Lifecycle events beyond this ticket's scope are audited, acknowledged, ignored."""
    response = await register(client, email="mystery@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)

    body = webhook_event_body(
        "evt_future_1",
        "customer.subscription.deleted",
        _dt(EVENT_CREATED),
        {"subscription": "sub_fake_1", "metadata": {"account_id": account_id}},
    )
    webhook = await _post_event(client, body)

    assert webhook.status_code == 200, webhook.text
    membership = await client.get("/api/me/membership", headers=auth)
    assert membership.json()["status"] == "free"

    rows = await _audit_rows(app, "evt_future_1")
    assert [(row.type, row.applied) for row in rows] == [("customer.subscription.deleted", False)]


class _CaptureHandler(logging.Handler):
    """Formats records exactly like production and keeps the parsed JSON lines."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.entries: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))


@contextlib.contextmanager
def _capture_json_logs() -> Iterator[list[dict]]:
    handler = _CaptureHandler()
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield handler.entries
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


async def test_state_transitions_and_outcomes_are_logged_with_the_stripe_event_id(
    client: AsyncClient,
) -> None:
    """AC7: every webhook decision is a structured line carrying the provider event id."""
    response = await register(client, email="logged@example.com")
    account_id = response.json()["account"]["id"]
    body = checkout_completed_body(
        "evt_logged_1", account_id, created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )

    with _capture_json_logs() as entries:
        assert (await _post_event(client, body)).status_code == 200
        assert (await _post_event(client, body)).status_code == 200

    transition = next(entry for entry in entries if entry["message"] == "billing_membership_changed")
    assert transition["event_id"] == "evt_logged_1"
    assert transition["event_type"] == "checkout.session.completed"
    assert transition["account_id"] == account_id
    assert transition["subscription_status"] == "active"
    assert transition["outcome"] == "applied"

    duplicate = next(entry for entry in entries if entry["message"] == "billing_event_duplicate_ignored")
    assert duplicate["event_id"] == "evt_logged_1"
    assert duplicate["outcome"] == "duplicate"


async def test_stale_event_outcome_is_logged_with_the_stripe_event_id(client: AsyncClient) -> None:
    """The out-of-order guard leaves an audit log line naming the skipped event."""
    response = await register(client, email="logged-stale@example.com")
    account_id = response.json()["account"]["id"]

    newest = checkout_completed_body(
        "evt_logged_new",
        account_id,
        created=_dt("2026-01-15T10:00:00+00:00"),
        period_end=_dt(PERIOD_END),
    )
    assert (await _post_event(client, newest)).status_code == 200

    older = checkout_completed_body(
        "evt_logged_old",
        account_id,
        created=_dt("2026-01-15T09:00:00+00:00"),
        period_end=_dt("2026-01-30T09:00:00+00:00"),
    )
    with _capture_json_logs() as entries:
        assert (await _post_event(client, older)).status_code == 200

    stale = next(entry for entry in entries if entry["message"] == "billing_event_stale_ignored")
    assert stale["event_id"] == "evt_logged_old"
    assert stale["outcome"] == "stale"


async def test_gateway_failure_answers_retryable_5xx_and_leaves_no_trace(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """AC6: the webhook neither blocks nor half-applies; the provider retries the event.

    A gateway that fails before decoding must surface a 5xx (Stripe retries) and write
    nothing at all - so the retry of the SAME event still lands cleanly.
    """
    response = await register(client, email="retry@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    body = checkout_completed_body(
        "evt_flaky", account_id, created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )
    gateway = adapters.billing_gateway
    outage = AppError(503, ErrorCode.SERVICE_UNAVAILABLE, "订阅支付服务暂时不可用")
    gateway.webhook_fail_with = outage  # type: ignore[attr-defined]

    failed = await _post_event(client, body)
    assert failed.status_code == 503, failed.text
    assert failed.json()["error"]["code"] == "service_unavailable"
    assert await _audit_rows(app, "evt_flaky") == []

    gateway.webhook_fail_with = None  # type: ignore[attr-defined]
    retried = await _post_event(client, body)
    assert retried.status_code == 200, retried.text
    membership = await client.get("/api/me/membership", headers=auth)
    assert membership.json()["status"] == "active"


async def test_checkout_event_for_an_unknown_account_is_audited_but_not_applied(
    client: AsyncClient, app: FastAPI
) -> None:
    """A paid event naming a deleted/unknown Account leaves no orphan subscription.

    The audit row still records the provider event (disputes must stay traceable), and
    the route answers 2xx so Stripe stops retrying an event that will never resolve.
    """
    body = checkout_completed_body(
        "evt_ghost_1", "acct-does-not-exist", created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )

    webhook = await _post_event(client, body)

    assert webhook.status_code == 200, webhook.text
    rows = await _audit_rows(app, "evt_ghost_1")
    assert [(row.account_id, row.applied) for row in rows] == [("acct-does-not-exist", False)]


async def test_newer_checkout_event_reactivates_and_updates_the_existing_subscription(
    client: AsyncClient, app: FastAPI
) -> None:
    """One Account, one subscription row: a fresh payment lifts it back to Active."""
    from app.modules.billing.models import Subscription

    response = await register(client, email="renew@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    async with app.state.sessionmaker() as session:
        session.add(
            Subscription(
                account_id=account_id,
                provider_customer_id="cus_old",
                provider_subscription_id="sub_old",
                status="canceled",
                current_period_end=_dt("2026-01-20T09:00:00+00:00"),
                price_id="price_fake_monthly",
            )
        )
        await session.commit()

    body = checkout_completed_body(
        "evt_renew_1",
        account_id,
        created=_dt("2026-01-15T11:00:00+00:00"),
        period_end=_dt(PERIOD_END),
        subscription_id="sub_renewed",
    )
    webhook = await _post_event(client, body)

    assert webhook.status_code == 200, webhook.text
    membership = await client.get("/api/me/membership", headers=auth)
    assert membership.json() == {
        "status": "active",
        "period_end": PERIOD_END,
        "cancel_at_period_end": False,
        "is_vip": True,
        "portal_url": "/api/billing/portal",
    }

    async with app.state.sessionmaker() as session:
        rows = (
            await session.scalars(select(Subscription).where(Subscription.account_id == account_id))
        ).all()
    assert len(rows) == 1
    assert rows[0].provider_subscription_id == "sub_renewed"


async def test_bad_signature_is_rejected_and_changes_nothing(
    client: AsyncClient, app: FastAPI
) -> None:
    """AC5: an event that fails the signature gate is a 400 and touches no data at all."""
    response = await register(client, email="attacker@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    body = checkout_completed_body(
        "evt_evil", account_id, created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )

    forged = await client.post(
        "/api/billing/webhook", content=body, headers={"stripe-signature": "t=1768471200,v1=deadbeef"}
    )

    assert forged.status_code == 400, forged.text
    assert forged.json()["error"]["code"] == "invalid_signature"

    unsigned = await client.post("/api/billing/webhook", content=body)
    assert unsigned.status_code == 400, unsigned.text

    membership = await client.get("/api/me/membership", headers=auth)
    assert membership.json()["status"] == "free"
    assert await _audit_rows(app, "evt_evil") == []


def _bare_settings(**overrides: object):
    from app.config import Settings

    values: dict[str, object] = {
        "_env_file": None,
        "env": "test",
        "secret_key": "test-only-secret",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_stripe_gateway_verifies_and_decodes_without_touching_the_sdk() -> None:
    """The production adapter's webhook gate is pure stdlib HMAC - no SDK, no network."""
    from app.adapters.stripe_billing import StripeBillingGateway

    gateway = StripeBillingGateway(_bare_settings(stripe_webhook_secret="whsec_live"))
    body = checkout_completed_body(
        "evt_live_1",
        "acct-7",
        created=_dt(EVENT_CREATED),
        period_end=_dt(PERIOD_END),
        subscription_id="sub_live",
        customer_id="cus_live",
    )

    event = gateway.verify_webhook(payload=body, signature=sign_webhook(body, secret="whsec_live"))

    assert event.event_id == "evt_live_1"
    assert event.type == "checkout.session.completed"
    assert event.created == _dt(EVENT_CREATED)
    assert event.account_id == "acct-7"
    assert event.provider_subscription_id == "sub_live"
    assert event.provider_customer_id == "cus_live"
    assert event.current_period_end == _dt(PERIOD_END)
    assert event.price_id == "price_fake_monthly"


def test_stripe_gateway_rejects_events_signed_with_the_wrong_secret() -> None:
    from app.adapters.stripe_billing import StripeBillingGateway

    gateway = StripeBillingGateway(_bare_settings(stripe_webhook_secret="whsec_live"))
    body = checkout_completed_body(
        "evt_evil_2", "acct-7", created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )

    with pytest.raises(AppError) as raised:
        gateway.verify_webhook(payload=body, signature=sign_webhook(body, secret="whsec_wrong"))

    assert raised.value.status == 400
    assert raised.value.code == "invalid_signature"


def test_stripe_gateway_rejects_a_tampered_body_under_a_valid_signature() -> None:
    from app.adapters.stripe_billing import StripeBillingGateway

    gateway = StripeBillingGateway(_bare_settings(stripe_webhook_secret="whsec_live"))
    body = checkout_completed_body(
        "evt_tamper_1", "acct-7", created=_dt(EVENT_CREATED), period_end=_dt(PERIOD_END)
    )
    signature = sign_webhook(body, secret="whsec_live")
    tampered = body.replace(b"acct-7", b"acct-2")

    with pytest.raises(AppError) as raised:
        gateway.verify_webhook(payload=tampered, signature=signature)

    assert raised.value.status == 400
    assert raised.value.code == "invalid_signature"


def test_stripe_gateway_rejects_an_unreadable_body_under_a_valid_signature() -> None:
    from app.adapters.stripe_billing import StripeBillingGateway

    gateway = StripeBillingGateway(_bare_settings(stripe_webhook_secret="whsec_live"))
    body = b"this is not a Stripe event"

    with pytest.raises(AppError) as raised:
        gateway.verify_webhook(payload=body, signature=sign_webhook(body, secret="whsec_live"))

    assert raised.value.status == 400
    assert raised.value.code == "invalid_request"


def test_stripe_gateway_without_webhook_secret_reports_unavailable() -> None:
    """No secret configured = no key to check against: 503 (retryable), never a blind accept."""
    from app.adapters.stripe_billing import StripeBillingGateway

    gateway = StripeBillingGateway(_bare_settings())

    with pytest.raises(AppError) as raised:
        gateway.verify_webhook(payload=b"{}", signature="t=1,v1=x")

    assert raised.value.status == 503
    assert raised.value.code == "service_unavailable"
