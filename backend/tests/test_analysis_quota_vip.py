"""VIP Membership lifts the daily Quota: observed at the in-process HTTP seam.

Membership is granted the way production grants it: a signature-verified
``checkout.session.completed`` POST to ``/api/billing/webhook`` through the fake
BillingGateway, plus seeded Subscription rows for the statuses P2-04's state machine
will produce later (trial_ending / past_due / canceled). Only external behaviour is
asserted: HTTP status codes, response schemas and the derived reads at ``/api/me``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from app.container import Adapters
from app.modules.billing.models import Subscription
from fastapi import FastAPI
from httpx import AsyncClient

from tests.auth_flows import verified_account
from tests.fakes import checkout_completed_body, sample_video, sign_webhook

PASSWORD = "correct-horse"
TERMINAL = {"completed", "failed"}
EVENT_CREATED = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 2, 14, 9, 0, tzinfo=UTC)


def _url(platform_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={platform_video_id}"


async def _register(
    client: AsyncClient, adapters: Adapters, email: str
) -> tuple[dict[str, str], str]:
    """Analysis needs a verified Account; the id comes back from ``GET /api/me``."""
    headers = await verified_account(client, adapters, email=email, password=PASSWORD)
    me = await client.get("/api/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["account"]["id"]


async def _activate_membership(client: AsyncClient, account_id: str) -> None:
    """The P2-01/P2-02 upgrade path: a verified checkout event makes the Account Active."""
    body = checkout_completed_body(
        "evt_vip_checkout_1", account_id, created=EVENT_CREATED, period_end=PERIOD_END
    )
    response = await client.post(
        "/api/billing/webhook", content=body, headers={"stripe-signature": sign_webhook(body)}
    )
    assert response.status_code == 200, response.text


async def _seed_subscription(app: FastAPI, account_id: str, status: str) -> None:
    """Record the subscription state the full webhook state machine (P2-04) will write."""
    async with app.state.sessionmaker() as session:
        session.add(
            Subscription(
                account_id=account_id,
                stripe_customer_id="cus_fake_1",
                stripe_subscription_id=f"sub_{status}_{account_id[:8]}",
                status=status,
                current_period_end=PERIOD_END,
                price_id="price_fake_monthly",
            )
        )
        await session.commit()


async def _resolve(
    client: AsyncClient, adapters: Adapters, platform_video_id: str
) -> str:
    url = _url(platform_video_id)
    adapters.video_source.videos[url] = sample_video(platform_video_id=platform_video_id)  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _create(
    client: AsyncClient, headers: dict[str, str], video_id: str, *, force: bool = False
) -> httpx.Response:
    return await client.post(
        "/api/analyses", json={"video_id": video_id, "force": force}, headers=headers
    )


async def _me(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/api/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["quota"]


async def _get(client: AsyncClient, headers: dict[str, str], analysis_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _wait_terminal(
    client: AsyncClient, headers: dict[str, str], analysis_id: str, *, limit_seconds: float = 5.0
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_seconds
    while loop.time() < deadline:
        body = await _get(client, headers, analysis_id)
        if body["status"] in TERMINAL:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"analysis {analysis_id} did not reach a terminal status")


async def _create_completed(
    client: AsyncClient, adapters: Adapters, headers: dict[str, str], video_id: str
) -> str:
    """Create one Analysis, wait for it to settle, then step past the creation throttle."""
    created = await _create(client, headers, video_id)
    assert created.status_code == 201, created.text
    analysis_id = created.json()["id"]
    await _wait_terminal(client, headers, analysis_id)
    adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]
    return analysis_id


async def _spend_free_quota(
    client: AsyncClient, adapters: Adapters, headers: dict[str, str], prefix: str
) -> None:
    """Exhaust the free daily allowance of 3 so the fourth attempt shows the gate."""
    for index in range(3):
        video_id = await _resolve(client, adapters, f"{prefix}{index + 1:04}")
        await _create_completed(client, adapters, headers, video_id)


async def test_active_subscription_creates_analyses_beyond_the_daily_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC1: an Active subscriber runs more Analyses per day than the free limit of 3."""
    headers, account_id = await _register(client, adapters, "vip@example.com")
    await _activate_membership(client, account_id)

    for index in range(4):
        video_id = await _resolve(client, adapters, "vipvid" + f"{index + 1:05d}")
        await _create_completed(client, adapters, headers, video_id)

    quota = await _me(client, headers)
    assert quota["used"] == 4


async def test_trial_ending_subscription_is_exempt_from_the_daily_quota(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """AC2: an unfinished trial (trial_ending) grants VIP Membership too."""
    headers, account_id = await _register(client, adapters, "trial@example.com")
    await _seed_subscription(app, account_id, "trial_ending")

    for index in range(4):
        video_id = await _resolve(client, adapters, f"trialid{index + 1:04}")
        await _create_completed(client, adapters, headers, video_id)

    assert (await _me(client, headers))["used"] == 4


async def test_past_due_subscription_is_not_exempt_from_the_daily_quota(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """AC2: payment trouble (past_due) loses the exemption."""
    headers, account_id = await _register(client, adapters, "dunning@example.com")
    await _seed_subscription(app, account_id, "past_due")

    await _spend_free_quota(client, adapters, headers, "pastdue")

    fourth = await _create(client, headers, await _resolve(client, adapters, "pastdue0004"))
    assert fourth.status_code == 429, fourth.text
    assert fourth.json()["error"]["code"] == "quota_exhausted"


async def test_canceled_subscription_kept_until_period_end_is_not_exempt(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """AC2: a canceled subscription is not VIP (P2-04 will flip it only pre-period-end)."""
    headers, account_id = await _register(client, adapters, "quitter@example.com")
    await _seed_subscription(app, account_id, "canceled")

    await _spend_free_quota(client, adapters, headers, "cancel0")

    fourth = await _create(client, headers, await _resolve(client, adapters, "cancel00004"))
    assert fourth.status_code == 429, fourth.text
    assert fourth.json()["error"]["code"] == "quota_exhausted"


async def test_vip_quota_snapshot_reports_the_unlimited_sentinel_with_membership(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC3: /api/me quota carries the sentinel daily_limit next to the membership status."""
    headers, account_id = await _register(client, adapters, "sentinel@example.com")
    await _activate_membership(client, account_id)
    video_id = await _resolve(client, adapters, "sentinel001")
    await _create_completed(client, adapters, headers, video_id)

    quota = await _me(client, headers)
    assert quota == {
        "daily_limit": -1,
        "used": 1,
        "remaining": -1,
        "resets_at": "2026-01-16T00:00:00+08:00",
        "membership": "active",
    }


async def test_analysis_create_response_includes_quota_snapshot_and_membership(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC3: the create response schema returns the snapshot alongside membership."""
    headers, account_id = await _register(client, adapters, "created@example.com")
    await _activate_membership(client, account_id)
    video_id = await _resolve(client, adapters, "created0001")

    created = await _create(client, headers, video_id)
    assert created.status_code == 201, created.text

    assert created.json()["membership"] == "active"
    quota = created.json()["quota"]
    assert quota["daily_limit"] == -1
    assert quota["remaining"] == -1
    assert quota["membership"] == "active"


async def test_free_account_quota_snapshot_keeps_numeric_limit_and_free_membership(
    client: AsyncClient, adapters: Adapters
) -> None:
    """The same snapshot without membership: numeric cap today, "free" status."""
    headers, _ = await _register(client, adapters, "plain@example.com")

    quota = await _me(client, headers)
    assert quota["daily_limit"] == 3
    assert quota["remaining"] == 3
    assert quota["membership"] == "free"


async def test_failed_vip_analysis_releases_the_reservation(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC4: VIP status never bypasses the rollback: a failure leaves no count behind."""
    adapters.summarizer.error = RuntimeError("upstream exploded")  # type: ignore[attr-defined]
    headers, account_id = await _register(client, adapters, "crash@example.com")
    await _activate_membership(client, account_id)
    video_id = await _resolve(client, adapters, "crashvid001")

    analysis_id = await _create_completed(client, adapters, headers, video_id)

    assert (await _get(client, headers, analysis_id))["status"] == "failed"
    quota = await _me(client, headers)
    assert quota["used"] == 0
    assert quota["daily_limit"] == -1


async def test_vip_double_click_reuses_the_active_analysis_without_reserving_twice(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC6: two tabs of the same VIP create still reserve exactly one unit."""
    adapters.summarizer.delay_seconds = 0.05  # type: ignore[attr-defined]
    headers, account_id = await _register(client, adapters, "tabs@example.com")
    await _activate_membership(client, account_id)
    video_id = await _resolve(client, adapters, "tabvid00001")

    responses = await asyncio.gather(_create(client, headers, video_id), _create(client, headers, video_id))

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 201], [response.text for response in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert responses[0].json()["quota"]["daily_limit"] == -1
    assert (await _me(client, headers))["used"] == 1
    await _wait_terminal(client, headers, responses[0].json()["id"])
