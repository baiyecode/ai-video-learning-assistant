"""Download acceptance tests, exercised through the in-process HTTP seam.

No sockets: ``FakeMediaStore`` writes fixed bytes, and the gated store blocks inside
the download so intermediate states can be observed deterministically.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from app.modules.media.models import Download
from app.ports import ResolvedVideo
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.fakes import make_fake_adapters, sample_video

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TERMINAL = {"ready", "failed", "expired"}


async def _resolved_video_id(client: AsyncClient, adapters: Adapters) -> str:
    adapters.video_source.videos = {YOUTUBE_URL: sample_video()}  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _create(client: AsyncClient, video_id: str, format_id: str = "bestaudio"):
    return await client.post(
        "/api/downloads", json={"video_id": video_id, "format_id": format_id}
    )


async def _wait_idle(app: FastAPI) -> None:
    manager = getattr(app.state, "download_manager", None)
    assert manager is not None, "a download should have created the manager"
    await asyncio.wait_for(manager.wait_idle(), timeout=5)


async def _get(
    client: AsyncClient,
    download_id: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    response = await client.get(f"/api/downloads/{download_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _await_status(
    client: AsyncClient,
    download_id: str,
    expected: set[str],
    *,
    headers: dict[str, str] | None = None,
    wait_seconds: float = 3.0,
) -> dict:
    deadline = time.monotonic() + wait_seconds
    last: dict | None = None
    while time.monotonic() < deadline:
        last = await _get(client, download_id, headers=headers)
        if last["status"] in expected:
            return last
        await asyncio.sleep(0.005)
    raise AssertionError(f"status never reached {expected}; last={last}")


async def _await_terminal(
    client: AsyncClient,
    download_id: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    return await _await_status(client, download_id, TERMINAL, headers=headers)


async def _download_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        return int(await session.scalar(select(func.count()).select_from(Download)) or 0)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _timestamp(value: str) -> float:
    parsed = _parse(value)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()


class GatedMediaStore:
    """Blocks inside each phase until the test releases it."""

    content: bytes = b"gated-media-bytes"

    def __init__(self) -> None:
        self.phases: list[tuple[str, float]] = []
        self.entered_downloading = asyncio.Event()
        self.entered_merging = asyncio.Event()
        self.resume_downloading = asyncio.Event()
        self.resume_merging = asyncio.Event()

    async def download(
        self,
        *,
        video: ResolvedVideo,
        format_id: str,
        dest_dir: Path,
        on_progress: Callable[[str, float], None],
    ) -> Path:
        self.phases.append(("downloading", 0.25))
        on_progress("downloading", 0.25)
        self.entered_downloading.set()
        await self.resume_downloading.wait()

        self.phases.append(("merging", 0.6))
        on_progress("merging", 0.6)
        self.entered_merging.set()
        await self.resume_merging.wait()

        on_progress("merging", 1.0)
        dest_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - tiny test write
        target = dest_dir / "gated.mp4"
        target.write_bytes(self.content)  # noqa: ASYNC240
        return target


@asynccontextmanager
async def _client_for(settings: Settings, adapters: Adapters) -> AsyncIterator[tuple[AsyncClient, FastAPI]]:
    app = create_app(settings=settings, adapters=adapters)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http, app


async def test_visitor_creates_download_and_gets_ready_with_signed_url(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)

    created = await _create(client, video_id, "bestaudio")

    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    assert body["progress"] == 0
    assert body["error"] is None
    assert body["download_url"] is None
    assert body["url_expires_at"] is None
    assert body["file_expires_at"] is None
    assert body["attempts"] == 0
    assert body["can_retry"] is False
    assert body["video_id"] == video_id
    assert body["format_id"] == "bestaudio"

    await _wait_idle(app)
    final = await _await_terminal(client, body["id"])

    assert final["status"] == "ready"
    assert final["progress"] == 1.0
    assert final["error"] is None
    assert final["file_name"].endswith(".mp4")
    assert final["file_size"] == len(b"fake-media-bytes")
    assert final["ready_at"]
    assert final["download_url"].startswith(f"/api/downloads/{body['id']}/file?")
    assert "sig=" in final["download_url"]
    # 15-minute signed URL, 1-hour file retention, both measured from ready_at.
    assert _timestamp(final["url_expires_at"]) - _timestamp(final["ready_at"]) == pytest.approx(900)
    assert _timestamp(final["file_expires_at"]) - _timestamp(final["ready_at"]) == pytest.approx(3600)
    # Visitors complete the whole flow with no Authorization header.
    assert "authorization" not in {key.lower() for key in client.headers}
    # The client IP is captured for the per-IP limits added in #6.
    async with app.state.sessionmaker() as session:
        row = await session.get(Download, body["id"])
        assert row is not None
        assert row.visitor_ip == "127.0.0.1"
        assert row.account_id is None


async def test_download_reports_queued_downloading_merging_ready_in_order(settings: Settings) -> None:
    store = GatedMediaStore()
    async with _client_for(settings, make_fake_adapters(media_store=store)) as (client, app):
        adapters = app.state.adapters
        video_id = await _resolved_video_id(client, adapters)
        created = await _create(client, video_id, "bestaudio")
        assert created.status_code == 202
        download_id = created.json()["id"]

        await asyncio.wait_for(store.entered_downloading.wait(), timeout=5)
        downloading = await _await_status(client, download_id, {"downloading"})
        assert downloading["progress"] == pytest.approx(0.25)

        store.resume_downloading.set()
        await asyncio.wait_for(store.entered_merging.wait(), timeout=5)
        merging = await _await_status(client, download_id, {"merging"})
        assert merging["progress"] == pytest.approx(0.6)

        store.resume_merging.set()
        await _wait_idle(app)
        ready = await _await_status(client, download_id, {"ready"})
        assert ready["progress"] == 1.0


async def test_signed_url_serves_file_and_stops_after_expiry(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)
    download_id = (await _create(client, video_id)).json()["id"]
    await _wait_idle(app)
    ready = await _await_terminal(client, download_id)
    url = ready["download_url"]
    clock = adapters.clock

    served = await client.get(url)
    assert served.status_code == 200
    assert served.content == b"fake-media-bytes"
    assert "attachment" in served.headers["content-disposition"]

    tampered = url[:-1] + ("0" if url[-1] != "0" else "1")
    forged = await client.get(tampered)
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "invalid_signature"

    clock.advance(seconds=901)  # type: ignore[attr-defined]
    expired = await client.get(url)
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "file_expired"

    # A fresh status read re-signs a new URL while the file is still retained.
    refreshed = await _get(client, download_id)
    assert refreshed["status"] == "ready"
    assert refreshed["download_url"] != url
    assert (await client.get(refreshed["download_url"])).status_code == 200

    clock.advance(seconds=45 * 60 + 1)  # type: ignore[attr-defined]  # past 1-hour retention
    gone = await client.get(f"/api/downloads/{download_id}")
    assert gone.status_code == 410
    assert gone.json()["error"]["code"] == "file_expired"
    stale = await client.get(refreshed["download_url"])
    assert stale.status_code == 410
    assert stale.json()["error"]["code"] == "file_expired"


async def test_failure_surfaces_a_chinese_reason_without_leaking_details(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)
    adapters.media_store.fail_with = RuntimeError("ffmpeg exploded at line 42")  # type: ignore[attr-defined]

    download_id = (await _create(client, video_id)).json()["id"]
    await _wait_idle(app)
    failed = await _await_terminal(client, download_id)

    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "download_failed"
    assert failed["error"]["message"]
    assert any("\u4e00" <= char <= "\u9fff" for char in failed["error"]["message"])
    assert "exploded" not in str(failed)
    assert failed["download_url"] is None
    assert failed["can_retry"] is True


async def test_create_rejects_unknown_video(client: AsyncClient) -> None:
    response = await _create(client, "does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "video_not_found"


async def test_create_rejects_unknown_format_and_stale_snapshot(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)

    unknown = await _create(client, video_id, "no-such-format")
    assert unknown.status_code == 409
    error = unknown.json()["error"]
    assert error["code"] == "formats_expired"
    assert error["details"]["video_id"] == video_id

    adapters.clock.advance(seconds=601)  # type: ignore[attr-defined]
    stale = await _create(client, video_id, "bestaudio")
    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "formats_expired"
    assert error["details"]["video_id"] == video_id
    assert await _download_count(app) == 0


async def test_retry_requeues_a_failed_download_then_succeeds(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)
    adapters.media_store.fail_with = RuntimeError("disk full")  # type: ignore[attr-defined]
    download_id = (await _create(client, video_id)).json()["id"]
    await _wait_idle(app)
    assert (await _await_terminal(client, download_id))["status"] == "failed"

    adapters.media_store.fail_with = None  # type: ignore[attr-defined]
    retried = await client.post(f"/api/downloads/{download_id}/retry")

    assert retried.status_code == 202
    body = retried.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 1
    assert body["error"] is None

    await _wait_idle(app)
    ready = await _await_status(client, download_id, {"ready"})
    assert ready["file_size"] == len(b"fake-media-bytes")


async def test_retry_is_capped_at_three_attempts(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)
    adapters.media_store.fail_with = RuntimeError("upstream error")  # type: ignore[attr-defined]
    download_id = (await _create(client, video_id)).json()["id"]
    await _wait_idle(app)
    await _await_terminal(client, download_id)

    for attempt in (1, 2, 3):
        response = await client.post(f"/api/downloads/{download_id}/retry")
        assert response.status_code == 202
        assert response.json()["attempts"] == attempt
        await _wait_idle(app)
        assert (await _await_terminal(client, download_id))["status"] == "failed"

    rejected = await client.post(f"/api/downloads/{download_id}/retry")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "download_failed"
    assert (await _get(client, download_id))["can_retry"] is False


async def test_logged_in_download_still_works_and_records_the_account(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    video_id = await _resolved_video_id(client, adapters)
    registered = await client.post(
        "/api/auth/register",
        json={"email": "downloader@example.com", "password": "correct-horse"},
    )
    assert registered.status_code == 201, registered.text
    account_id = registered.json()["account"]["id"]
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    created = await client.post(
        "/api/downloads",
        json={"video_id": video_id, "format_id": "bestaudio"},
        headers=headers,
    )

    assert created.status_code == 202
    await _wait_idle(app)
    await _await_terminal(client, created.json()["id"], headers=headers)
    async with app.state.sessionmaker() as session:
        row = await session.get(Download, created.json()["id"])
        assert row is not None
        assert row.account_id == account_id


async def test_unknown_download_and_retry_are_not_found(client: AsyncClient) -> None:
    status = await client.get("/api/downloads/nope")
    assert status.status_code == 404
    assert status.json()["error"]["code"] == "download_not_found"

    retry = await client.post("/api/downloads/nope/retry")
    assert retry.status_code == 404
    assert retry.json()["error"]["code"] == "download_not_found"
