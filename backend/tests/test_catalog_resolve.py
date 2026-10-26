"""Video resolve acceptance tests, exercised through the in-process HTTP seam.

Every test uses ``FakeVideoSource``: no sockets and no real platform calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from app.container import Adapters
from app.modules.catalog.models import Subtitle, Video
from app.ports import ResolvedVideo, SubtitleTrack, VideoFormat, VideoUnavailableError
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
BILIBILI_URL = "https://www.bilibili.com/video/BV1xx411c7mD"


def youtube_video(**overrides: object) -> ResolvedVideo:
    video = ResolvedVideo(
        platform="youtube",
        platform_video_id="dQw4w9WgXcQ",
        title="测试视频：从零开始",
        duration_seconds=3725,
        webpage_url=YOUTUBE_URL,
        uploader="示例作者",
        thumbnail_url="https://img.example/cover.jpg",
        formats=(
            VideoFormat(
                format_id="137",
                label="1080p",
                ext="mp4",
                width=1920,
                height=1080,
                filesize=104_857_600,
                has_video=True,
                has_audio=False,
            ),
            VideoFormat(
                format_id="140",
                label="仅音频",
                ext="m4a",
                filesize=5_242_880,
                has_video=False,
                has_audio=True,
            ),
        ),
        subtitles=(SubtitleTrack(language="zh-Hans", name="中文（简体）"),),
    )
    return replace(video, **overrides)


def bilibili_video(**overrides: object) -> ResolvedVideo:
    video = ResolvedVideo(
        platform="bilibili",
        platform_video_id="BV1xx411c7mD",
        title="B 站示例视频",
        duration_seconds=125,
        webpage_url=BILIBILI_URL,
        uploader="UP 主",
        formats=(VideoFormat(format_id="80", label="1080P 大会员", ext="mp4", height=1080),),
        subtitles=(SubtitleTrack(language="zh-CN", name="中文（自动）", is_automatic=True),),
    )
    return replace(video, **overrides)


async def _resolve(client: AsyncClient, url: str):
    return await client.post("/api/videos/resolve", json={"url": url})


async def _video_row_count(app: FastAPI, platform: str, platform_video_id: str) -> int:
    async with app.state.sessionmaker() as session:
        stmt = (
            select(func.count())
            .select_from(Video)
            .where(Video.platform == platform, Video.platform_video_id == platform_video_id)
        )
        return int((await session.execute(stmt)).scalar_one())


async def _subtitle_row_count(app: FastAPI, platform_video_id: str) -> int:
    async with app.state.sessionmaker() as session:
        stmt = (
            select(func.count())
            .select_from(Subtitle)
            .join(Video, Subtitle.video_id == Video.id)
            .where(Video.platform_video_id == platform_video_id)
        )
        return int((await session.execute(stmt)).scalar_one())


async def test_resolve_youtube_returns_metadata_formats_and_subtitles(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]

    response = await _resolve(client, YOUTUBE_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["video"]["platform"] == "youtube"
    assert body["video"]["platform_video_id"] == "dQw4w9WgXcQ"
    assert body["video"]["title"] == "测试视频：从零开始"
    assert body["video"]["duration_seconds"] == 3725
    assert body["video"]["thumbnail_url"] == "https://img.example/cover.jpg"
    assert body["video"]["is_drm"] is False
    assert body["video"]["is_members_only"] is False

    assert [fmt["format_id"] for fmt in body["formats"]] == ["137", "140"]
    video_format = body["formats"][0]
    assert video_format == {
        "format_id": "137",
        "label": "1080p",
        "ext": "mp4",
        "resolution": "1080p",
        "width": 1920,
        "height": 1080,
        "filesize": 104_857_600,
        "has_video": True,
        "has_audio": False,
    }
    assert body["formats"][1]["resolution"] == "仅音频"

    assert body["subtitles"] == [
        {"language": "zh-Hans", "name": "中文（简体）", "is_automatic": False}
    ]
    assert body["can_analyze"] is True
    assert "仅限个人备份或已获授权内容" in body["resolve_notice"]


async def test_resolve_bilibili_returns_platform_and_formats(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.videos = {BILIBILI_URL: bilibili_video()}  # type: ignore[attr-defined]

    response = await _resolve(client, "https://m.bilibili.com/video/BV1xx411c7mD?p=3&vd_source=x")

    assert response.status_code == 200
    body = response.json()
    assert body["video"]["platform"] == "bilibili"
    assert body["video"]["title"] == "B 站示例视频"
    assert body["formats"][0]["label"] == "1080P 大会员"


async def test_short_links_tracking_params_and_quality_urls_share_one_video(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    bili = bilibili_video()
    adapters.video_source.videos = {  # type: ignore[attr-defined]
        BILIBILI_URL: bili,
        "https://b23.tv/abcDEF": bili,
    }
    variants = [
        "https://b23.tv/abcDEF",
        "https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333.999&vd_source=abc",
        "https://m.bilibili.com/video/BV1xx411c7mD?p=2&t=30",
        "https://www.bilibili.com/video/BV1xx411c7mD?p=1&t=30",
    ]

    video_ids = set()
    for url in variants:
        response = await _resolve(client, url)
        assert response.status_code == 200, url
        video_ids.add(response.json()["video"]["id"])

    assert len(video_ids) == 1
    assert await _video_row_count(app, "bilibili", "BV1xx411c7mD") == 1


async def test_youtube_variants_share_one_video(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    variants = [
        "https://youtu.be/dQw4w9WgXcQ?si=share&t=42",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=4&pp=abc",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    ]

    video_ids = set()
    for url in variants:
        response = await _resolve(client, url)
        assert response.status_code == 200, url
        video_ids.add(response.json()["video"]["id"])

    assert len(video_ids) == 1
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.bilibili.com/list/watchlater?bvid=BV1xx411c7mD",
        "https://space.bilibili.com/123/favlist?fid=456",
    ],
)
async def test_playlists_and_collections_are_rejected(client: AsyncClient, url: str) -> None:
    response = await _resolve(client, url)

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "playlist_not_supported"
    assert body["message"]
    assert body["request_id"]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/1",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://live.bilibili.com/12345",
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
async def test_unsupported_and_live_urls_are_rejected(client: AsyncClient, url: str) -> None:
    response = await _resolve(client, url)

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "unsupported_url"
    assert body["message"]


async def test_unavailable_video_is_rejected(client: AsyncClient, adapters: Adapters) -> None:
    adapters.video_source.resolve_error = VideoUnavailableError("private video")  # type: ignore[attr-defined]

    response = await _resolve(client, YOUTUBE_URL)

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "video_unavailable"
    assert body["message"]


@pytest.mark.parametrize(
    ("flags", "code"),
    [
        ({"is_drm": True}, "drm_protected"),
        ({"is_members_only": True}, "members_only"),
    ],
)
async def test_drm_and_members_only_content_is_rejected(
    client: AsyncClient,
    adapters: Adapters,
    app: FastAPI,
    flags: dict[str, bool],
    code: str,
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video(**flags)}  # type: ignore[attr-defined]

    response = await _resolve(client, YOUTUBE_URL)

    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == code
    assert body["message"]
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 0


async def test_missing_url_is_an_invalid_request(client: AsyncClient) -> None:
    response = await client.post("/api/videos/resolve", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_get_returns_cached_metadata_and_formats(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    resolved = (await _resolve(client, YOUTUBE_URL)).json()
    video_id = resolved["video"]["id"]

    response = await client.get(f"/api/videos/{video_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["video"]["id"] == video_id
    assert body["video"]["title"] == resolved["video"]["title"]
    assert [fmt["format_id"] for fmt in body["formats"]] == ["137", "140"]
    assert body["formats_expired"] is False
    assert body["formats_fetched_at"]


async def test_formats_snapshot_expires_after_ten_minutes(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    video_id = (await _resolve(client, YOUTUBE_URL)).json()["video"]["id"]
    clock = adapters.clock

    clock.advance(seconds=599)  # type: ignore[attr-defined]
    fresh = await client.get(f"/api/videos/{video_id}")
    assert fresh.status_code == 200

    clock.advance(seconds=2)  # type: ignore[attr-defined]
    expired = await client.get(f"/api/videos/{video_id}")
    assert expired.status_code == 409
    error = expired.json()["error"]
    assert error["code"] == "formats_expired"
    assert error["message"]
    assert error["details"]["video_id"] == video_id

    refreshed = await _resolve(client, YOUTUBE_URL)
    assert refreshed.status_code == 200
    assert refreshed.json()["video"]["id"] == video_id

    after = await client.get(f"/api/videos/{video_id}")
    assert after.status_code == 200
    assert after.json()["formats_fetched_at"] != fresh.json()["formats_fetched_at"]


async def test_get_unknown_video_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/videos/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "video_not_found"


async def test_adapter_failure_maps_to_a_stable_error(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.resolve_error = RuntimeError("yt-dlp exploded at line 42")  # type: ignore[attr-defined]

    response = await _resolve(client, YOUTUBE_URL)

    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "resolve_failed"
    assert "yt-dlp exploded" not in response.text
    assert isinstance(body, dict)
    assert body["message"]


async def test_resolve_can_analyse_is_false_without_subtitles(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video(subtitles=())}  # type: ignore[attr-defined]

    body = (await _resolve(client, YOUTUBE_URL)).json()

    assert body["subtitles"] == []
    assert body["can_analyze"] is False


async def test_concurrent_resolve_of_new_video_persists_one_subtitle(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """Two tabs resolving the same new Video: both succeed and share one Subtitle."""
    source = adapters.video_source
    source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    # Both requests are past their "no Subtitle yet" read before either inserts.
    source.subtitle_barrier = asyncio.Barrier(2)  # type: ignore[attr-defined]

    responses = await asyncio.wait_for(
        asyncio.gather(_resolve(client, YOUTUBE_URL), _resolve(client, YOUTUBE_URL)), timeout=10
    )

    assert [response.status_code for response in responses] == [200, 200], [
        response.text for response in responses
    ]
    bodies = [response.json() for response in responses]
    assert bodies[0]["video"]["id"] == bodies[1]["video"]["id"]
    assert bodies[0]["can_analyze"] is True
    assert bodies[1]["can_analyze"] is True
    assert len(source.subtitle_calls) == 2  # type: ignore[attr-defined]
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 1
    assert await _subtitle_row_count(app, "dQw4w9WgXcQ") == 1

    exported = await client.get(f"/api/videos/{bodies[0]['video']['id']}/subtitles?format=srt")
    assert exported.status_code == 200
    assert "示例字幕" in exported.text


async def test_concurrent_resolve_without_subtitles_stays_subtitle_free(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: youtube_video(subtitles=())}  # type: ignore[attr-defined]

    responses = await asyncio.wait_for(
        asyncio.gather(_resolve(client, YOUTUBE_URL), _resolve(client, YOUTUBE_URL)), timeout=10
    )

    assert [response.status_code for response in responses] == [200, 200], [
        response.text for response in responses
    ]
    bodies = [response.json() for response in responses]
    assert bodies[0]["video"]["id"] == bodies[1]["video"]["id"]
    assert bodies[0]["can_analyze"] is False
    assert bodies[1]["can_analyze"] is False
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 1
    assert await _subtitle_row_count(app, "dQw4w9WgXcQ") == 0


async def test_subtitle_fetch_failure_adopts_the_concurrently_persisted_subtitle(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """The failing side reports the Subtitle the other request persisted while it fetched."""
    source = adapters.video_source
    source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    entered = asyncio.Event()
    release = asyncio.Event()
    source.subtitle_entered = entered  # type: ignore[attr-defined]
    # The first fetch blocks, then fails; the second fetch succeeds and wins the row.
    source.subtitle_fail_on_call = 1  # type: ignore[attr-defined]
    source.subtitle_fail_gate = release  # type: ignore[attr-defined]

    failing = asyncio.create_task(_resolve(client, YOUTUBE_URL))
    await asyncio.wait_for(entered.wait(), timeout=10)  # failing side is inside fetch

    succeeding = await _resolve(client, YOUTUBE_URL)
    assert succeeding.status_code == 200, succeeding.text

    release.set()
    failed = await asyncio.wait_for(failing, timeout=10)

    assert failed.status_code == 200, failed.text
    assert succeeding.json()["can_analyze"] is True
    assert failed.json()["can_analyze"] is True
    assert failed.json()["video"]["id"] == succeeding.json()["video"]["id"]
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 1
    assert await _subtitle_row_count(app, "dQw4w9WgXcQ") == 1


async def test_empty_caption_result_reports_the_concurrently_persisted_subtitle(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """An empty captions payload must report the row that ends up persisted (#54/#51).

    The empty side reads "no Subtitle yet", waits while the other resolve commits the
    winning row, then answers empty. Its answer must reflect the final persisted row,
    not the pre-fetch observation.
    """
    source = adapters.video_source
    source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    entered = asyncio.Event()
    release = asyncio.Event()
    source.subtitle_entered = entered  # type: ignore[attr-defined]
    source.subtitle_empty_on_call = 1  # type: ignore[attr-defined]
    source.subtitle_empty_gate = release  # type: ignore[attr-defined]

    empty = asyncio.create_task(_resolve(client, YOUTUBE_URL))
    await asyncio.wait_for(entered.wait(), timeout=10)  # the empty side is inside fetch

    succeeding = await _resolve(client, YOUTUBE_URL)
    assert succeeding.status_code == 200, succeeding.text
    assert succeeding.json()["can_analyze"] is True

    release.set()
    emptied = await asyncio.wait_for(empty, timeout=10)

    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["can_analyze"] is True
    assert emptied.json()["video"]["id"] == succeeding.json()["video"]["id"]
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 1
    assert await _subtitle_row_count(app, "dQw4w9WgXcQ") == 1

    exported = await client.get(
        f"/api/videos/{succeeding.json()['video']['id']}/subtitles?format=srt"
    )
    assert exported.status_code == 200
    assert "示例字幕" in exported.text


async def test_concurrent_resolve_of_url_variants_shares_one_video_and_subtitle(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """Two URL variants of one new Video racing: both succeed on one Video/Subtitle row."""
    source = adapters.video_source
    source.videos = {YOUTUBE_URL: youtube_video()}  # type: ignore[attr-defined]
    # Both variants normalise to YOUTUBE_URL, so the fake sees one Video; the barrier
    # holds both requests past their "no Subtitle yet" read before either inserts.
    source.subtitle_barrier = asyncio.Barrier(2)  # type: ignore[attr-defined]
    short_link = "https://youtu.be/dQw4w9WgXcQ?si=share"
    watch_link = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=4"

    responses = await asyncio.wait_for(
        asyncio.gather(_resolve(client, short_link), _resolve(client, watch_link)), timeout=10
    )

    assert [response.status_code for response in responses] == [200, 200], [
        response.text for response in responses
    ]
    bodies = [response.json() for response in responses]
    assert bodies[0]["video"]["id"] == bodies[1]["video"]["id"]
    assert bodies[0]["can_analyze"] is True
    assert bodies[1]["can_analyze"] is True
    assert await _video_row_count(app, "youtube", "dQw4w9WgXcQ") == 1
    assert await _subtitle_row_count(app, "dQw4w9WgXcQ") == 1
