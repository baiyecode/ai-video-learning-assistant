"""Download stability and resource boundaries (#6).

Every scenario runs through the in-process HTTP seam with fake adapters; queue
behaviour is observed with a store that blocks until the test releases it, so
ordering and concurrency are deterministic (no sleeps asserting timing).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from app.modules.media.manager import DownloadManager
from app.modules.media.models import Download, DownloadStatus
from app.ports import ResolvedVideo, VideoFormat
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.auth_flows import logged_in_account
from tests.fakes import make_fake_adapters, sample_video

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
GIB = 1024**3
TERMINAL = {"ready", "failed", "expired"}


# --------------------------------------------------------------------------- helpers


@asynccontextmanager
async def _client_for(
    settings: Settings, adapters: Adapters
) -> AsyncIterator[tuple[AsyncClient, FastAPI]]:
    app = create_app(settings=settings, adapters=adapters)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http, app


async def _resolve(
    client: AsyncClient,
    adapters: Adapters,
    video: ResolvedVideo | None = None,
) -> str:
    adapters.video_source.videos = {YOUTUBE_URL: video or sample_video()}  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _create(
    client: AsyncClient,
    video_id: str,
    format_id: str = "bestaudio",
    *,
    headers: dict[str, str] | None = None,
    ip: str | None = None,
) -> httpx.Response:
    merged = dict(headers or {})
    if ip is not None:
        merged["X-Forwarded-For"] = ip
    return await client.post(
        "/api/downloads",
        json={"video_id": video_id, "format_id": format_id},
        headers=merged,
    )


async def _get(
    client: AsyncClient,
    download_id: str,
    *,
    headers: dict[str, str] | None = None,
    ip: str | None = None,
) -> dict:
    merged = dict(headers or {})
    if ip is not None:
        merged["X-Forwarded-For"] = ip
    response = await client.get(f"/api/downloads/{download_id}", headers=merged)
    assert response.status_code == 200, response.text
    return response.json()


async def _download_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        return int(await session.scalar(select(func.count()).select_from(Download)) or 0)


async def _wait_idle(app: FastAPI) -> None:
    manager = getattr(app.state, "download_manager", None)
    assert manager is not None, "a download should have created the manager"
    await asyncio.wait_for(manager.wait_idle(), timeout=5)


async def _await_idle(app: FastAPI) -> None:
    manager = getattr(app.state, "download_manager", None)
    if manager is not None:
        await asyncio.wait_for(manager.wait_idle(), timeout=5)


async def _wait_until(predicate: Callable[[], bool], *, wait_seconds: float = 2.0, label: str = "") -> None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"condition never became true: {label}")


async def _wait_status(
    client: AsyncClient,
    download_id: str,
    expected: set[str],
    *,
    headers: dict[str, str] | None = None,
    ip: str | None = None,
    wait_seconds: float = 3.0,
) -> dict:
    deadline = time.monotonic() + wait_seconds
    last: dict | None = None
    while time.monotonic() < deadline:
        last = await _get(client, download_id, headers=headers, ip=ip)
        if last["status"] in expected:
            return last
        await asyncio.sleep(0.005)
    raise AssertionError(f"status never reached {expected}; last={last}")


async def _await_terminal(
    client: AsyncClient,
    download_id: str,
    *,
    headers: dict[str, str] | None = None,
    ip: str | None = None,
) -> dict:
    return await _wait_status(client, download_id, TERMINAL, headers=headers, ip=ip)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fast_settings(settings: Settings, **overrides: object) -> Settings:
    """Test settings that isolate the limit under test from the other caps."""
    base: dict[str, object] = {
        "download_global_concurrency": 5,
        "download_account_concurrency": 5,
        "download_visitor_concurrency": 5,
        "download_cleanup_interval_seconds": 60.0,
    }
    base.update(overrides)
    return settings.model_copy(update=base)


class BlockingMediaStore:
    """Records start order and blocks every download until ``release`` is set."""

    def __init__(self, content: bytes = b"blocking-media-bytes") -> None:
        self.content = content
        self.started: list[str] = []
        self.release = asyncio.Event()

    async def download(
        self,
        *,
        video: ResolvedVideo,
        format_id: str,
        dest_dir: Path,
        on_progress: Callable[[str, float], None],
    ) -> Path:
        self.started.append(Path(dest_dir).name)
        on_progress("downloading", 0.2)
        await self.release.wait()
        on_progress("merging", 1.0)
        dest_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - tiny test write
        target = dest_dir / "media.mp4"
        target.write_bytes(self.content)  # noqa: ASYNC240
        return target


# --------------------------------------------------------------- creation limits


async def test_create_rejects_video_longer_than_two_hours(settings: Settings) -> None:
    adapters = make_fake_adapters()
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(
            client, adapters, sample_video(duration_seconds=7201)
        )

        response = await _create(client, video_id)

        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "download_too_long"
        assert any("\u4e00" <= char <= "\u9fff" for char in error["message"])
        assert error["details"]["max_duration_seconds"] == 7200
        assert error["details"]["duration_seconds"] == 7201
        assert await _download_count(app) == 0


async def test_two_hour_video_is_accepted_at_the_boundary(settings: Settings) -> None:
    adapters = make_fake_adapters()
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(
            client, adapters, sample_video(duration_seconds=7200)
        )

        response = await _create(client, video_id)
        assert response.status_code == 202, response.text

        await _wait_idle(app)
        assert (await _await_terminal(client, response.json()["id"]))["status"] == "ready"


async def test_create_rejects_a_format_with_known_oversize_filesize(settings: Settings) -> None:
    adapters = make_fake_adapters()
    oversized = 2 * GIB + 1
    video = replace(
        sample_video(),
        formats=(
            VideoFormat(
                format_id="1080p",
                label="1080P",
                ext="mp4",
                height=1080,
                filesize=oversized,
            ),
            VideoFormat(format_id="bestaudio", label="仅音频", ext="m4a", has_video=False),
        ),
    )
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters, video)

        rejected = await _create(client, video_id, "1080p")
        assert rejected.status_code == 422, rejected.text
        error = rejected.json()["error"]
        assert error["code"] == "download_too_large"
        assert error["details"]["max_file_size_bytes"] == 2 * GIB
        assert error["details"]["filesize"] == oversized

        # Unknown sizes cannot be rejected up-front; they are caught after download.
        accepted = await _create(client, video_id, "bestaudio")
        assert accepted.status_code == 202, accepted.text
        await _wait_idle(app)
        assert (await _await_terminal(client, accepted.json()["id"]))["status"] == "ready"


async def test_exactly_two_gib_is_accepted_at_the_boundary(settings: Settings) -> None:
    adapters = make_fake_adapters()
    video = replace(
        sample_video(),
        formats=(VideoFormat(format_id="exact", label="2GB", ext="mp4", filesize=2 * GIB),),
    )
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters, video)

        response = await _create(client, video_id, "exact")
        assert response.status_code == 202, response.text
        await _wait_idle(app)
        assert (await _await_terminal(client, response.json()["id"]))["status"] == "ready"


async def test_visitor_hourly_creation_cap_rejects_with_retry_after(settings: Settings) -> None:
    adapters = make_fake_adapters()
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        clock = adapters.clock

        for _ in range(5):
            created = await _create(client, video_id)
            assert created.status_code == 202, created.text
            await _wait_idle(app)
            await _await_terminal(client, created.json()["id"])
            # #12: 3 creations per IP per minute; stay below it to reach the hourly cap.
            clock.advance(seconds=61)  # type: ignore[attr-defined]

        rejected = await _create(client, video_id)
        assert rejected.status_code == 429, rejected.text
        error = rejected.json()["error"]
        assert error["code"] == "download_limit_reached"
        assert any("\u4e00" <= char <= "\u9fff" for char in error["message"])
        assert error["details"]["retry_after"] > 0
        reset_at = _parse(error["details"]["reset_at"])
        reset_at = reset_at if reset_at.tzinfo else reset_at.replace(tzinfo=UTC)
        assert reset_at > clock.now()  # type: ignore[attr-defined]
        assert error["details"]["limit"] == 5

        # One hour later the window has rolled over and a new creation is allowed.
        clock.advance(seconds=3601)  # type: ignore[attr-defined]
        video_id = await _resolve(client, adapters)  # refresh the 10-minute format snapshot
        accepted = await _create(client, video_id)
        assert accepted.status_code == 202, accepted.text


async def test_account_downloads_are_not_counted_against_the_visitor_cap(settings: Settings) -> None:
    adapters = make_fake_adapters()
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        auth = await logged_in_account(client, email="capped@example.com", password="correct-horse")

        for _ in range(6):
            created = await _create(client, video_id, headers=auth)
            assert created.status_code == 202, created.text
            await _wait_idle(app)
            await _await_terminal(client, created.json()["id"], headers=auth)
            # #12: 3 creations per IP per minute, independent of the visitor cap.
            adapters.clock.advance(seconds=61)  # type: ignore[attr-defined]


# ------------------------------------------------------------ queue and limits


async def test_global_concurrency_queues_extra_work_in_creation_order(settings: Settings) -> None:
    store = BlockingMediaStore()
    adapters = make_fake_adapters(media_store=store)
    tuned = _fast_settings(settings, download_global_concurrency=2)
    async with _client_for(tuned, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        ids: list[str] = []
        for index in range(4):
            # Distinct IPs isolate the global cap from the per-IP visitor cap.
            created = await _create(client, video_id, ip=f"10.0.0.{index + 1}")
            assert created.status_code == 202, created.text
            ids.append(created.json()["id"])

        await _wait_until(lambda: len(store.started) == 2, label="two downloads running")
        assert store.started == ids[:2]

        third = await _get(client, ids[2], ip="10.0.0.3")
        assert third["status"] == "queued"
        assert third["queue_position"] == 1
        fourth = await _get(client, ids[3], ip="10.0.0.4")
        assert fourth["status"] == "queued"
        assert fourth["queue_position"] == 2
        running = await _get(client, ids[0], ip="10.0.0.1")
        assert running["queue_position"] is None

        store.release.set()
        await _wait_idle(app)

        # The first two are FIFO. The queued pair is dispatched in order too, but
        # each job awaits its own database read before calling the store, so their
        # first adapter calls may interleave: assert dispatch completeness, not
        # scheduler timing.
        assert store.started[:2] == ids[:2]
        assert set(store.started[2:]) == set(ids[2:])
        assert len(store.started) == 4
        for index, download_id in enumerate(ids):
            assert (
                await _await_terminal(client, download_id, ip=f"10.0.0.{index + 1}")
            )["status"] == "ready"


async def test_visitor_concurrency_is_one_per_ip(settings: Settings) -> None:
    store = BlockingMediaStore()
    adapters = make_fake_adapters(media_store=store)
    tuned = _fast_settings(settings, download_visitor_concurrency=1)
    async with _client_for(tuned, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        first = await _create(client, video_id)
        second = await _create(client, video_id)
        assert first.status_code == 202 and second.status_code == 202

        await _wait_until(lambda: len(store.started) == 1, label="one visitor download running")
        assert store.started == [first.json()["id"]]
        queued = await _get(client, second.json()["id"])
        assert queued["status"] == "queued"
        assert queued["queue_position"] == 1

        store.release.set()
        await _wait_idle(app)
        assert store.started == [first.json()["id"], second.json()["id"]]
        assert (await _await_terminal(client, second.json()["id"]))["status"] == "ready"


async def test_account_concurrency_is_two(settings: Settings) -> None:
    store = BlockingMediaStore()
    adapters = make_fake_adapters(media_store=store)
    tuned = _fast_settings(
        settings,
        download_account_concurrency=2,
        download_visitor_concurrency=1,
    )
    async with _client_for(tuned, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        auth = await logged_in_account(client, email="queue@example.com", password="correct-horse")

        ids: list[str] = []
        for _ in range(3):
            created = await _create(client, video_id, headers=auth)
            assert created.status_code == 202, created.text
            ids.append(created.json()["id"])

        await _wait_until(lambda: len(store.started) == 2, label="two account downloads running")
        assert store.started == ids[:2]
        third = await _get(client, ids[2], headers=auth)
        assert third["status"] == "queued"
        assert third["queue_position"] == 1

        store.release.set()
        await _wait_idle(app)
        assert store.started[:2] == ids[:2]
        assert set(store.started[2:]) == set(ids[2:])
        for download_id in ids:
            assert (await _await_terminal(client, download_id, headers=auth))["status"] == "ready"


# --------------------------------------------------------------- resource checks


async def test_oversized_downloaded_file_is_deleted_and_fails(settings: Settings) -> None:
    store = BlockingMediaStore(content=b"x" * 16)
    store.release.set()
    adapters = make_fake_adapters(media_store=store)
    tuned = _fast_settings(settings, download_max_file_size_bytes=8)
    async with _client_for(tuned, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        created = await _create(client, video_id)
        assert created.status_code == 202
        await _wait_idle(app)

        failed = await _await_terminal(client, created.json()["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "download_too_large"
        assert any("\u4e00" <= char <= "\u9fff" for char in failed["error"]["message"])
        assert failed["download_url"] is None
        assert failed["can_retry"] is True

        async with app.state.sessionmaker() as session:
            row = await session.get(Download, created.json()["id"])
            assert row is not None
            assert row.file_path is None
        leftovers = [path for path in tuned.media_dir.rglob("*") if path.is_file()]
        assert leftovers == []


# ------------------------------------------------------------------- HTTP Range


async def test_file_endpoint_supports_range_resume(settings: Settings) -> None:
    content = b"0123456789abcdef"
    store = BlockingMediaStore(content=content)
    store.release.set()
    adapters = make_fake_adapters(media_store=store)
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        created = await _create(client, video_id)
        await _wait_idle(app)
        ready = await _await_terminal(client, created.json()["id"])
        url = ready["download_url"]

        full = await client.get(url)
        assert full.status_code == 200
        assert full.headers["accept-ranges"] == "bytes"
        assert full.content == content

        middle = await client.get(url, headers={"Range": "bytes=4-7"})
        assert middle.status_code == 206
        assert middle.headers["content-range"] == "bytes 4-7/16"
        assert middle.headers["content-length"] == "4"
        assert middle.headers["accept-ranges"] == "bytes"
        assert middle.content == b"4567"

        resumed = await client.get(url, headers={"Range": "bytes=8-"})
        assert resumed.status_code == 206
        assert resumed.headers["content-range"] == "bytes 8-15/16"
        assert resumed.content == b"89abcdef"
        # Reassembling the two halves yields the full response bytes.
        head = await client.get(url, headers={"Range": "bytes=0-7"})
        assert head.content + resumed.content == content

        suffix = await client.get(url, headers={"Range": "bytes=-4"})
        assert suffix.status_code == 206
        assert suffix.content == b"cdef"

        beyond = await client.get(url, headers={"Range": "bytes=100-200"})
        assert beyond.status_code == 416
        assert beyond.headers["content-range"] == "bytes */16"


# --------------------------------------------------------- retention / cleanup


async def test_cleanup_expired_removes_the_file_and_marks_the_task_expired(
    settings: Settings,
) -> None:
    store = BlockingMediaStore()
    store.release.set()
    adapters = make_fake_adapters(media_store=store)
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        created = await _create(client, video_id)
        await _wait_idle(app)
        ready = await _await_terminal(client, created.json()["id"])
        assert ready["status"] == "ready"

        async with app.state.sessionmaker() as session:
            row = await session.get(Download, created.json()["id"])
            assert row is not None and row.file_path is not None
            retained = Path(row.file_path)
        assert retained.is_file()  # noqa: ASYNC240 - tiny test artifact

        adapters.clock.advance(seconds=3601)  # type: ignore[attr-defined]
        manager = app.state.download_manager
        assert await manager.cleanup_expired() == 1

        assert not retained.exists()  # noqa: ASYNC240 - tiny test artifact
        async with app.state.sessionmaker() as session:
            row = await session.get(Download, created.json()["id"])
            assert row is not None
            assert row.status == DownloadStatus.EXPIRED
            assert row.file_path is None

        gone = await client.get(f"/api/downloads/{created.json()['id']}")
        assert gone.status_code == 410
        assert gone.json()["error"]["code"] == "file_expired"

        # Idempotent: nothing left to clean.
        assert await manager.cleanup_expired() == 0


async def test_periodic_cleanup_runs_without_an_explicit_call(settings: Settings) -> None:
    store = BlockingMediaStore()
    store.release.set()
    adapters = make_fake_adapters(media_store=store)
    tuned = _fast_settings(settings, download_cleanup_interval_seconds=0.02)
    async with _client_for(tuned, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        created = await _create(client, video_id)
        await _wait_idle(app)
        await _await_terminal(client, created.json()["id"])

        adapters.clock.advance(seconds=3601)  # type: ignore[attr-defined]

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            async with app.state.sessionmaker() as session:
                row = await session.get(Download, created.json()["id"])
            if row is not None and row.status == DownloadStatus.EXPIRED:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("periodic cleanup never marked the task expired")


# --------------------------------------------------------------- restart recovery


async def test_manager_start_marks_interrupted_downloads_failed(settings: Settings) -> None:
    adapters = make_fake_adapters()
    async with _client_for(settings, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        now = adapters.clock.now()
        ids: dict[str, str] = {}
        async with app.state.sessionmaker() as session:
            rows: list[tuple[str, Download]] = []
            for status in (
                DownloadStatus.QUEUED,
                DownloadStatus.DOWNLOADING,
                DownloadStatus.MERGING,
                DownloadStatus.READY,
            ):
                row = Download(
                    video_id=video_id,
                    format_id="bestaudio",
                    status=str(status),
                    progress=0.0,
                    attempts=0,
                    visitor_ip="203.0.113.7",
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                rows.append((str(status), row))
            await session.commit()
            ids = {status: row.id for status, row in rows}

        manager = DownloadManager(
            sessionmaker=app.state.sessionmaker,
            adapters=app.state.adapters,
            settings=app.state.settings,
        )
        await manager.start()

        async with app.state.sessionmaker() as session:
            for status in ("queued", "downloading", "merging"):
                row = await session.get(Download, ids[status])
                assert row is not None
                assert row.status == DownloadStatus.FAILED
                assert row.error_code == "download_failed"
                assert row.error_message == "服务重启导致任务中断，请重试"
            untouched = await session.get(Download, ids["ready"])
            assert untouched is not None
            assert untouched.status == DownloadStatus.READY

        failed = await _get(client, ids["downloading"], ip="203.0.113.7")
        assert failed["status"] == "failed"
        assert failed["can_retry"] is True
        assert failed["error"]["message"] == "服务重启导致任务中断，请重试"

        # Startup recovery is one-shot: a later start does not touch new work.
        new_row = Download(
            video_id=video_id,
            format_id="bestaudio",
            status=DownloadStatus.QUEUED,
            progress=0.0,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        async with app.state.sessionmaker() as session:
            session.add(new_row)
            await session.commit()
            new_id = new_row.id
        await manager.start()
        async with app.state.sessionmaker() as session:
            row = await session.get(Download, new_id)
            assert row is not None and row.status == DownloadStatus.QUEUED


# ----------------------------------------------------------------------- retries


async def test_retry_waits_for_a_free_slot_instead_of_bypassing_limits(settings: Settings) -> None:
    store = BlockingMediaStore()
    adapters = make_fake_adapters(media_store=store)
    tuned = _fast_settings(settings, download_visitor_concurrency=1)
    async with _client_for(tuned, adapters) as (client, app):
        video_id = await _resolve(client, adapters)
        running = await _create(client, video_id)
        assert running.status_code == 202
        await _wait_until(lambda: len(store.started) == 1, label="first download running")

        now = adapters.clock.now()
        async with app.state.sessionmaker() as session:
            failed_row = Download(
                video_id=video_id,
                format_id="bestaudio",
                status=DownloadStatus.FAILED,
                progress=0.0,
                attempts=0,
                error_code="download_failed",
                error_message="下载失败，请稍后重试",
                visitor_ip="127.0.0.1",
                created_at=now,
                updated_at=now,
            )
            session.add(failed_row)
            await session.commit()
            failed_id = failed_row.id

        retried = await client.post(f"/api/downloads/{failed_id}/retry")
        assert retried.status_code == 202, retried.text
        assert retried.json()["status"] == "queued"
        assert retried.json()["attempts"] == 1
        assert retried.json()["queue_position"] == 1

        # Same IP already has one running task: the retry waits, it does not start.
        await asyncio.sleep(0.02)
        assert store.started == [running.json()["id"]]

        store.release.set()
        await _wait_idle(app)
        assert store.started == [running.json()["id"], failed_id]
        assert (await _wait_status(client, failed_id, {"ready"}))["status"] == "ready"
