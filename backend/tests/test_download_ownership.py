"""Download ownership and client-identity hardening.

A Download id must not leak another Visitor's or Account's task: the lookup answers
with the same ``download_not_found`` a missing row returns. Rate-limit keys and
Visitor ownership use the address appended by our reverse proxy, never a
client-supplied ``X-Forwarded-For`` prefix.
"""

from __future__ import annotations

from app.container import Adapters
from httpx import AsyncClient

from tests.fakes import sample_video

PASSWORD = "correct-horse"
YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _proxy_ip(leftmost: str, real: str = "198.51.100.7") -> dict[str, str]:
    """A spoofed client prefix followed by the hop our proxy appended."""
    return {"X-Forwarded-For": f"{leftmost}, {real}"}


async def _resolve(client: AsyncClient, adapters: Adapters, key: str = "ownvideo001") -> str:
    url = f"https://www.youtube.com/watch?v={key}"
    adapters.video_source.videos[url] = sample_video(platform_video_id=key)  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _register(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create(
    client: AsyncClient,
    video_id: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    response = await client.post(
        "/api/downloads",
        json={"video_id": video_id, "format_id": "bestaudio"},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def test_visitor_download_is_only_visible_from_the_same_address(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters)
    download_id = await _create(client, video_id, headers=_proxy_ip("192.0.2.1"))

    own = await client.get(f"/api/downloads/{download_id}", headers=_proxy_ip("192.0.2.200"))
    assert own.status_code == 200
    assert own.json()["id"] == download_id

    other = await client.get(f"/api/downloads/{download_id}", headers=_proxy_ip("x", "203.0.113.9"))
    # Same answer as a missing id: a guessed id must not confirm existence.
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "download_not_found"

    retry = await client.post(
        f"/api/downloads/{download_id}/retry",
        headers=_proxy_ip("x", "203.0.113.9"),
    )
    assert retry.status_code == 404
    assert retry.json()["error"]["code"] == "download_not_found"


async def test_account_download_is_only_visible_to_its_owner(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters)
    owner = await _register(client, "owner@example.com")
    stranger = await _register(client, "stranger@example.com")
    download_id = await _create(client, video_id, headers=owner)

    assert (await client.get(f"/api/downloads/{download_id}", headers=owner)).status_code == 200

    for headers in (stranger, None):
        response = await client.get(f"/api/downloads/{download_id}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "download_not_found"

    denied = await client.post(f"/api/downloads/{download_id}/retry", headers=stranger)
    assert denied.status_code == 404

    # The owner reaches the real state (a ready task cannot be retried).
    allowed = await client.post(f"/api/downloads/{download_id}/retry", headers=owner)
    assert allowed.status_code == 409
    assert allowed.json()["error"]["code"] in {"download_not_ready", "download_failed"}


async def test_rate_limit_uses_the_proxy_appended_hop_not_a_spoofed_prefix(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters)

    for index in range(3):
        await _create(client, video_id, headers=_proxy_ip(f"192.0.2.{index + 1}"))

    rejected = await client.post(
        "/api/downloads",
        json={"video_id": video_id, "format_id": "bestaudio"},
        headers=_proxy_ip("192.0.2.99"),
    )
    assert rejected.status_code == 429, rejected.text
    assert rejected.json()["error"]["code"] == "too_many_requests"
    # A rotating client prefix must not open a new bucket.
    assert rejected.json()["error"]["details"]["scope"] == "downloads.create"


async def test_real_ip_header_from_the_proxy_wins(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters)
    proxy_headers = {"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "10.9.9.9"}
    download_id = await _create(client, video_id, headers=proxy_headers)

    own = await client.get(
        f"/api/downloads/{download_id}", headers={"X-Real-IP": "203.0.113.5"}
    )
    assert own.status_code == 200

    other = await client.get(
        f"/api/downloads/{download_id}", headers={"X-Real-IP": "203.0.113.6"}
    )
    assert other.status_code == 404
