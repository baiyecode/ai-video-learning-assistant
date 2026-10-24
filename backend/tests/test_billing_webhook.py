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

from app.container import Adapters
from app.errors import AppError, ErrorCode
from app.logging_setup import JsonFormatter
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from tests.fakes import checkout_completed_body, sign_webhook, webhook_event_body

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
