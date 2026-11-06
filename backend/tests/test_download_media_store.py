"""Production resolve/download chain with only the yt-dlp subprocess replaced."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app.adapters.fs_media_store import FsMediaStore
from app.adapters.ytdlp_source import YtDlpVideoSource
from app.config import Settings
from app.main import create_app
from asgi_lifespan import LifespanManager

from tests.fakes import make_fake_adapters

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def metadata() -> dict:
    return {
        "id": "dQw4w9WgXcQ",
        "extractor_key": "Youtube",
        "title": "Separate video and audio tracks",
        "duration": 120,
        "webpage_url": YOUTUBE_URL,
        "formats": [
            {"format_id": "137", "ext": "mp4", "height": 1080, "width": 1920,
             "vcodec": "avc1.640028", "acodec": "none", "filesize": 2000},
            {"format_id": "139", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.5",
             "abr": 48, "filesize": 400},
            {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2",
             "abr": 128, "filesize": 600},
            {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus",
             "abr": 160, "filesize": 700},
            {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1.42001E",
             "acodec": "mp4a.40.2", "filesize": 800},
        ],
    }


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch, metadata: dict) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("shutil.which", lambda executable: executable)

    async def spawn(*args: str, **kwargs):
        calls.append(args)
        if "--dump-single-json" in args:
            return SimpleNamespace(
                returncode=0,
                communicate=AsyncMock(return_value=(json.dumps(metadata).encode(), b"")),
            )
        destination = Path(args[args.index("-o") + 1])
        destination.with_name("media.mp4").write_bytes(b"merged-media")
        stdout = asyncio.StreamReader()
        stdout.feed_data(b"[download] 50%\n[Merger] Merging formats into media.mp4\n")
        stdout.feed_eof()
        return SimpleNamespace(stdout=stdout, wait=AsyncMock(return_value=0))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.mark.parametrize(
    ("format_index", "selector", "filesize", "has_video"),
    [(0, "137+140", 2600, True), (2, "140", 600, False), (4, "18", 800, True)],
)
async def test_snapshot_downloads_exact_tracks_without_changing_audio_or_muxed_formats(
    settings: Settings, commands: list[tuple[str, ...]],
    format_index: int, selector: str, filesize: int, has_video: bool,
) -> None:
    adapters = replace(
        make_fake_adapters(),
        video_source=YtDlpVideoSource(settings),
        media_store=FsMediaStore(settings),
    )
    app = create_app(settings=settings, adapters=adapters)
    async with LifespanManager(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        resolved = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
        assert resolved.status_code == 200, resolved.text
        body = resolved.json()
        video_format = body["formats"][format_index]
        assert video_format["format_id"] == selector
        assert video_format["has_video"] is has_video
        assert video_format["has_audio"] is True
        assert video_format["filesize"] == filesize
        created = await client.post(
            "/api/downloads",
            json={"video_id": body["video"]["id"], "format_id": video_format["format_id"]},
        )
        assert created.status_code == 202, created.text
        await asyncio.wait_for(app.state.download_manager.wait_idle(), timeout=5)
        ready = await client.get(f"/api/downloads/{created.json()['id']}")
        assert ready.json()["status"] == "ready"
        assert (await client.get(ready.json()["download_url"])).content == b"merged-media"

    assert len(commands) == 2
    download = commands[1]
    assert download[download.index("-f") + 1] == selector
    assert download[download.index("--merge-output-format") + 1] == "mp4"
    assert download[-1] == YOUTUBE_URL
    assert "--no-playlist" in download


@pytest.mark.parametrize(
    ("limit", "unknown_track", "status"),
    [(2600, None, 202), (2599, None, 422), (2001, 0, 202), (2001, 2, 202)],
)
async def test_combined_track_size_is_enforced_before_download(
    settings: Settings, metadata: dict, commands: list[tuple[str, ...]],
    limit: int, unknown_track: int | None, status: int,
) -> None:
    if unknown_track is not None:
        metadata["formats"][unknown_track].pop("filesize")
    settings = settings.model_copy(update={"download_max_file_size_bytes": limit})
    adapters = replace(
        make_fake_adapters(), video_source=YtDlpVideoSource(settings),
        media_store=FsMediaStore(settings),
    )
    app = create_app(settings=settings, adapters=adapters)
    async with LifespanManager(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        resolved = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
        assert resolved.status_code == 200
        body = resolved.json()
        assert body["formats"][0]["filesize"] == (2600 if unknown_track is None else None)
        created = await client.post(
            "/api/downloads", json={"video_id": body["video"]["id"], "format_id": "137+140"},
        )
        assert created.status_code == status, created.text
        if status == 422:
            assert created.json()["error"]["code"] == "download_too_large"
            assert created.json()["error"]["details"]["filesize"] == 2600
            assert len(commands) == 1  # No downloader was spawned.
        else:
            await asyncio.wait_for(app.state.download_manager.wait_idle(), timeout=5)
            ready = await client.get(f"/api/downloads/{created.json()['id']}")
            assert ready.json()["status"] == "ready"


async def test_audio_choice_is_deterministic_and_ignores_invalid_or_drm_tracks(
    settings: Settings, metadata: dict, commands: list[tuple[str, ...]],
) -> None:
    metadata["formats"].extend([
        {"format_id": "drm", "ext": "m4a", "vcodec": "none", "acodec": "aac",
         "abr": 999, "has_drm": True},
        {"ext": "m4a", "vcodec": "none", "acodec": "aac", "abr": 999},
        None,
    ])
    source = YtDlpVideoSource(settings)
    first = await source.resolve(YOUTUBE_URL)
    metadata["formats"].reverse()
    second = await source.resolve(YOUTUBE_URL)
    assert next(fmt for fmt in first.formats if fmt.height == 1080).format_id == "137+140"
    assert next(fmt for fmt in second.formats if fmt.height == 1080).format_id == "137+140"


@pytest.mark.parametrize("with_audio", [False, True])
async def test_silent_video_stays_silent_only_when_no_audio_track_exists(
    settings: Settings, metadata: dict, commands: list[tuple[str, ...]], with_audio: bool,
) -> None:
    metadata["formats"] = [metadata["formats"][0]] + (
        [metadata["formats"][3]] if with_audio else []
    )
    source = YtDlpVideoSource(settings)
    video = await source.resolve(YOUTUBE_URL)
    selected = video.formats[0]
    assert selected.format_id == ("137+251" if with_audio else "137")
    assert selected.has_audio is with_audio
    assert selected.filesize == (2700 if with_audio else 2000)
    await FsMediaStore(settings).download(
        video=video, format_id=selected.format_id, dest_dir=settings.media_dir / "silent",
        on_progress=lambda *_: None,
    )
    assert commands[-1][commands[-1].index("-f") + 1] == selected.format_id
