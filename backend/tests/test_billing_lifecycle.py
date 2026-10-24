"""Subscription lifecycle beyond first payment: failures, recovery, cancellations.

Everything is observed at the in-process HTTP seam: lifecycle events are POSTed to
``/api/billing/webhook`` through the fake BillingGateway exactly like Stripe delivers
them (signature header + Stripe-style body), and the derived truth is read back from
``GET /api/me/membership``. State only ever moves on events - no local guessing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest
from app.container import Adapters
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from tests.auth_flows import login as auth_login
from tests.auth_flows import register as auth_register
from tests.auth_flows import verified_account
from tests.fakes import (
    FAKE_PORTAL_URL,
    checkout_completed_body,
    lifecycle_event_body,
    sample_video,
    sign_webhook,
)

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


async def test_portal_endpoint_returns_the_gateway_portal_url(client: AsyncClient) -> None:
    """AC4: an Account with a subscription gets the self-service portal link from the gateway."""
    response = await register(client, email="portal@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)

    portal = await client.post("/api/billing/portal", headers=auth)

    assert portal.status_code == 200, portal.text
    assert portal.json() == {"url": FAKE_PORTAL_URL}


async def test_portal_requires_logging_in(client: AsyncClient) -> None:
    response = await client.post("/api/billing/portal")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "auth_required"


async def test_portal_without_a_subscription_is_an_understood_404(client: AsyncClient) -> None:
    """AC4: free Accounts get a stable code and a Chinese message, not a stack or a 500."""
    response = await register(client, email="nopay@example.com")
    auth = bearer(response)

    portal = await client.post("/api/billing/portal", headers=auth)

    assert portal.status_code == 404, portal.text
    error = portal.json()["error"]
    assert error["code"] == "subscription_not_found"
    assert "订阅" in error["message"]


@pytest.mark.parametrize("lifecycle_event", ["invoice.payment_failed", "customer.subscription.deleted"])
async def test_portal_stays_open_for_past_due_and_canceled_subscriptions(
    client: AsyncClient, lifecycle_event: str
) -> None:
    """Story 11/12: card updates and billing history live exactly when payments hurt."""
    response = await register(client, email=f"portal-{lifecycle_event}@example.com")
    account_id = response.json()["account"]["id"]
    auth = bearer(response)
    await _activate(client, account_id)
    later = lifecycle_event_body(
        f"evt_{lifecycle_event}_portal", lifecycle_event, _dt("2026-01-15T10:00:00+00:00"),
        account_id=account_id,
    )
    assert (await _post_event(client, later)).status_code == 200

    portal = await client.post("/api/billing/portal", headers=auth)

    assert portal.status_code == 200, portal.text
    assert portal.json() == {"url": FAKE_PORTAL_URL}


async def test_stripe_gateway_portal_reports_unavailable_without_configuration() -> None:
    """Production adapter parity with checkout: no keys or no customer = clear 503, no crash."""
    from app.adapters.stripe_billing import StripeBillingGateway
    from app.config import Settings
    from app.errors import AppError

    unconfigured = StripeBillingGateway(
        Settings(_env_file=None, env="test", secret_key="test-only-secret")
    )
    with pytest.raises(AppError) as raised:
        await unconfigured.create_portal(stripe_customer_id="cus_1", return_url="http://testserver/")
    assert raised.value.status == 503
    assert raised.value.code == "service_unavailable"

    keyed = StripeBillingGateway(
        Settings(_env_file=None, env="test", secret_key="test-only-secret", stripe_api_key="sk_test_x")
    )
    with pytest.raises(AppError) as raised:
        await keyed.create_portal(stripe_customer_id="", return_url="http://testserver/")
    assert raised.value.status == 503
    assert raised.value.code == "service_unavailable"


async def _create_analysis(client: AsyncClient, headers: dict[str, str], video_id: str) -> Any:
    return await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)


async def _wait_completed(client: AsyncClient, headers: dict[str, str], analysis_id: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline:
        response = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
        assert response.status_code == 200, response.text
        if response.json()["status"] == "completed":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"analysis {analysis_id} did not complete")


async def _resolve_video(
    client: AsyncClient, adapters: Adapters, headers: dict[str, str], platform_video_id: str
) -> str:
    url = f"https://www.youtube.com/watch?v={platform_video_id}"
    adapters.video_source.videos[url] = sample_video(platform_video_id=platform_video_id)  # type: ignore[attr-defined]
    resolved = await client.post("/api/videos/resolve", json={"url": url}, headers=headers)
    assert resolved.status_code == 200, resolved.text
    return resolved.json()["video"]["id"]


async def test_canceled_membership_downgrades_analysis_to_the_free_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC2: the deleted subscription needs no manual step - the very next Analysis is
    bound by the free daily Quota again (P2-03's derived VIP lifts off automatically)."""
    headers = await verified_account(client, adapters, email="downgraded@example.com")
    me = await client.get("/api/me", headers=headers)
    account_id = me.json()["account"]["id"]
    await _activate(client, account_id)

    for index in range(4):  # four completed Analyses: past the free limit, VIP carried it
        video_id = await _resolve_video(client, adapters, headers, f"lcdown0{index:04d}")
        created = await _create_analysis(client, headers, video_id)
        assert created.status_code == 201, created.text
        await _wait_completed(client, headers, created.json()["id"])
        adapters.clock.advance(seconds=10)

    deleted = lifecycle_event_body(
        "evt_lc_delete_final",
        "customer.subscription.deleted",
        _dt("2026-01-15T12:00:00+00:00"),
        account_id=account_id,
    )
    assert (await _post_event(client, deleted)).status_code == 200
    membership = await _membership(client, headers)
    assert membership == {
        "status": "canceled",
        "period_end": PERIOD_END,
        "portal_url": None,
        "is_vip": False,
    }

    fifth = await _create_analysis(
        client, headers, await _resolve_video(client, adapters, headers, "lcdown09999")
    )
    assert fifth.status_code == 429, fifth.text
    assert fifth.json()["error"]["code"] == "quota_exhausted"
    assert fifth.json()["error"]["details"]["daily_limit"] == 3
