"""Rate-limit acceptance tests through the in-process HTTP seam.

Defaults (spec §认证、配额与限流):
- ``POST /api/videos/resolve``: 10/min per IP
- ``POST /api/downloads``: 3/min per IP (the #6 hourly/concurrency caps stay)
- ``POST /api/auth/login``: 10/15min per IP
- ``POST /api/auth/register``: 5/hour per IP
- ``POST /api/analyses``: 1/10s per Account (reusing an existing Analysis is free)

Every rejection is ``429 too_many_requests`` with a ``Retry-After`` header and
``details: {scope, retry_after, reset_at}``. Time comes from the injected Clock.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.container import Adapters
from httpx import AsyncClient

from tests.fakes import sample_video

PASSWORD = "correct-horse"


def _assert_rate_limited(response: Any, *, scope: str, now: datetime) -> dict[str, Any]:
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "too_many_requests"
    assert any("\u4e00" <= char <= "\u9fff" for char in error["message"])
    details = error["details"]
    assert details["scope"] == scope
    assert details["retry_after"] > 0
    assert int(response.headers["retry-after"]) == details["retry_after"]
    reset_at = datetime.fromisoformat(details["reset_at"])
    assert reset_at > now
    return error


async def _register(client: AsyncClient, email: str = "learner@example.com") -> dict[str, str]:
    response = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _resolve(client: AsyncClient, adapters: Adapters, video_id: str = "rlvideo0001") -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    adapters.video_source.videos[url] = sample_video(  # type: ignore[attr-defined]
        platform_video_id=video_id
    )
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def test_resolve_is_limited_to_ten_per_minute_per_ip(
    client: AsyncClient, adapters: Adapters
) -> None:
    url = "https://www.youtube.com/watch?v=rlresolve01"
    adapters.video_source.videos[url] = sample_video(  # type: ignore[attr-defined]
        platform_video_id="rlresolve01"
    )
    for _ in range(10):
        response = await client.post("/api/videos/resolve", json={"url": url})
        assert response.status_code == 200, response.text

    rejected = await client.post("/api/videos/resolve", json={"url": url})
    _assert_rate_limited(rejected, scope="videos.resolve", now=adapters.clock.now())

    adapters.clock.advance(seconds=60)  # type: ignore[attr-defined]
    allowed = await client.post("/api/videos/resolve", json={"url": url})
    assert allowed.status_code == 200, allowed.text


async def test_resolve_limit_is_per_ip(client: AsyncClient, adapters: Adapters) -> None:
    url = "https://www.youtube.com/watch?v=rlperip0001"
    adapters.video_source.videos[url] = sample_video(  # type: ignore[attr-defined]
        platform_video_id="rlperip0001"
    )
    for _ in range(10):
        response = await client.post(
            "/api/videos/resolve", json={"url": url}, headers={"X-Forwarded-For": "10.0.0.7"}
        )
        assert response.status_code == 200, response.text

    blocked = await client.post(
        "/api/videos/resolve", json={"url": url}, headers={"X-Forwarded-For": "10.0.0.7"}
    )
    assert blocked.status_code == 429

    other = await client.post(
        "/api/videos/resolve", json={"url": url}, headers={"X-Forwarded-For": "10.0.0.8"}
    )
    assert other.status_code == 200, other.text


async def test_download_creation_is_limited_to_three_per_minute_per_ip(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters, "rldownload1")
    for _ in range(3):
        created = await client.post(
            "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}
        )
        assert created.status_code == 202, created.text

    rejected = await client.post(
        "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}
    )
    _assert_rate_limited(rejected, scope="downloads.create", now=adapters.clock.now())

    # One minute later the window opens again, but #6's hourly cap still applies.
    adapters.clock.advance(seconds=61)  # type: ignore[attr-defined]
    fresh = await client.post(
        "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}
    )
    assert fresh.status_code == 202, fresh.text


async def test_download_hourly_cap_still_reports_download_limit_reached(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters, "rlhourly001")
    for _ in range(5):
        created = await client.post(
            "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}
        )
        assert created.status_code == 202, created.text
        adapters.clock.advance(seconds=61)  # type: ignore[attr-defined]

    rejected = await client.post(
        "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}
    )
    assert rejected.status_code == 429, rejected.text
    assert rejected.json()["error"]["code"] == "download_limit_reached"


async def test_login_is_limited_to_ten_per_fifteen_minutes_per_ip(
    client: AsyncClient, adapters: Adapters
) -> None:
    await _register(client)

    for _ in range(10):
        attempt = await client.post(
            "/api/auth/login",
            json={"email": "learner@example.com", "password": "wrong-password"},
        )
        assert attempt.status_code == 401, attempt.text

    rejected = await client.post(
        "/api/auth/login", json={"email": "learner@example.com", "password": "wrong-password"}
    )
    _assert_rate_limited(rejected, scope="auth.login", now=adapters.clock.now())

    # The registered credentials work again once the window rolls over.
    adapters.clock.advance(seconds=15 * 60)  # type: ignore[attr-defined]
    allowed = await client.post(
        "/api/auth/login", json={"email": "learner@example.com", "password": PASSWORD}
    )
    assert allowed.status_code == 200, allowed.text


async def test_register_is_limited_to_five_per_hour_per_ip(
    client: AsyncClient, adapters: Adapters
) -> None:
    for index in range(5):
        response = await client.post(
            "/api/auth/register",
            json={"email": f"new{index}@example.com", "password": PASSWORD},
        )
        assert response.status_code == 201, response.text

    rejected = await client.post(
        "/api/auth/register", json={"email": "new5@example.com", "password": PASSWORD}
    )
    _assert_rate_limited(rejected, scope="auth.register", now=adapters.clock.now())

    adapters.clock.advance(seconds=3600)  # type: ignore[attr-defined]
    allowed = await client.post(
        "/api/auth/register", json={"email": "new5@example.com", "password": PASSWORD}
    )
    assert allowed.status_code == 201, allowed.text


async def test_new_analysis_is_limited_to_one_per_ten_seconds_per_account(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)
    first_video = await _resolve(client, adapters, "rlanalysis1")
    second_video = await _resolve(client, adapters, "rlanalysis2")

    first = await client.post("/api/analyses", json={"video_id": first_video}, headers=headers)
    assert first.status_code == 201, first.text

    rejected = await client.post(
        "/api/analyses", json={"video_id": second_video}, headers=headers
    )
    _assert_rate_limited(rejected, scope="analyses.create", now=adapters.clock.now())

    adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]
    allowed = await client.post(
        "/api/analyses", json={"video_id": second_video}, headers=headers
    )
    assert allowed.status_code == 201, allowed.text


async def test_analysis_rate_limit_does_not_block_reusing_an_existing_result(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "rlreuse0001")

    first = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert first.status_code == 201
    analysis_id = first.json()["id"]

    # Same Analysis while it is in progress: reuse must not hit the creation limit.
    second = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == analysis_id

    # Wait for completion, then reuse the completed result: still not a new Analysis.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        detail = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
        if detail.json()["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    third = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert third.status_code == 200, third.text
    assert third.json()["id"] == analysis_id


async def test_analysis_rate_limit_is_per_account(
    client: AsyncClient, adapters: Adapters
) -> None:
    first = await _register(client, "first@example.com")
    adapters.clock.advance(seconds=1)  # type: ignore[attr-defined]  # separate register window
    second = await _register(client, "second@example.com")
    adapters.clock.advance(seconds=1)  # type: ignore[attr-defined]

    video_id = await _resolve(client, adapters, "rlaccount01")
    assert (
        await client.post("/api/analyses", json={"video_id": video_id}, headers=first)
    ).status_code == 201
    assert (
        await client.post("/api/analyses", json={"video_id": video_id}, headers=second)
    ).status_code == 201


async def test_rate_limit_envelope_contains_reset_metadata(
    client: AsyncClient, adapters: Adapters
) -> None:
    url = "https://www.youtube.com/watch?v=rlenvelope1"
    adapters.video_source.videos[url] = sample_video(  # type: ignore[attr-defined]
        platform_video_id="rlenvelope1"
    )
    for _ in range(10):
        await client.post("/api/videos/resolve", json={"url": url})

    response = await client.post("/api/videos/resolve", json={"url": url})
    error = _assert_rate_limited(
        response, scope="videos.resolve", now=adapters.clock.now()
    )
    parsed = datetime.fromisoformat(error["details"]["reset_at"])
    assert parsed.tzinfo is not None
    # The first hit happened at ``now``; a 60-second window therefore resets at now+60.
    assert abs((parsed - adapters.clock.now()).total_seconds() - 60) < 1
    request_id = error["request_id"]
    assert request_id
    assert response.headers["x-request-id"] == request_id


async def test_analysis_rejections_before_creation_do_not_consume_the_creation_window(
    client: AsyncClient, adapters: Adapters
) -> None:
    """A reviewable rejection (unknown Video) never reserves a rate-limit slot."""
    headers = await _register(client)

    missing = await client.post("/api/analyses", json={"video_id": "nope"}, headers=headers)
    assert missing.status_code == 404

    video_id = await _resolve(client, adapters, "rlreject001")
    created = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert created.status_code == 201, created.text


async def test_rate_limiter_prunes_keys_whose_window_elapsed(settings) -> None:
    from app.ratelimit import RateLimiter, build_rules

    from tests.fakes import FrozenClock

    clock = FrozenClock()
    limiter = RateLimiter(clock=clock, rules=build_rules(settings))
    for index in range(50):
        limiter.hit("downloads.create", f"198.51.100.{index}")
    assert limiter.tracked_keys == 50

    clock.advance(seconds=61)
    limiter.hit("downloads.create", "203.0.113.1")

    # Recording prunes every key whose whole window has elapsed.
    assert limiter.tracked_keys == 1
