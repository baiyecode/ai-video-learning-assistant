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

from tests.fakes import checkout_completed_body, sample_video, sign_webhook

PASSWORD = "correct-horse"
TERMINAL = {"completed", "failed"}
EVENT_CREATED = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 2, 14, 9, 0, tzinfo=UTC)


def _url(platform_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={platform_video_id}"


async def _register(client: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    response = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["account"]["id"]


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


async def test_active_subscription_creates_analyses_beyond_the_daily_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    """AC1: an Active subscriber runs more Analyses per day than the free limit of 3."""
    headers, account_id = await _register(client, "vip@example.com")
    await _activate_membership(client, account_id)

    for index in range(4):
        video_id = await _resolve(client, adapters, f"vipvid{index + 1:05}")
        await _create_completed(client, adapters, headers, video_id)

    quota = await _me(client, headers)
    assert quota["used"] == 4
