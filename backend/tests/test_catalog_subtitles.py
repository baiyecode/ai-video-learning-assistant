"""Subtitle selection, persistence and export, exercised through the HTTP seam.

The production yt-dlp adapter is never exercised here: ``FakeVideoSource`` serves
canned payloads and records which track the service asked for.
"""

from __future__ import annotations

import re

import pytest
from app.container import Adapters
from app.modules.catalog import subtitles
from app.modules.catalog.models import Video
from app.ports import ResolvedVideo, SubtitlePayload, SubtitleTrack, VideoFormat
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

LONG_TEXT = (
    "这是一段很长的字幕文本，用来验证导出时不会截断内容。"
    "从零开始学习一门技术需要持续的练习与复盘，" * 12
)


def manual(language: str) -> SubtitleTrack:
    return SubtitleTrack(language=language, name=f"{language}（人工）", is_automatic=False)


def automatic(language: str) -> SubtitleTrack:
    return SubtitleTrack(language=language, name=f"{language}（自动）", is_automatic=True)


def video_with(*tracks: SubtitleTrack) -> ResolvedVideo:
    return ResolvedVideo(
        platform="youtube",
        platform_video_id="dQw4w9WgXcQ",
        title="字幕测试视频",
        duration_seconds=120,
        webpage_url=YOUTUBE_URL,
        uploader="示例作者",
        formats=(VideoFormat(format_id="137", label="1080p", ext="mp4", height=1080),),
        subtitles=tuple(tracks),
    )


def payload(track: SubtitleTrack, cues: list[tuple[float, float, str]]) -> SubtitlePayload:
    return SubtitlePayload(track=track, cues=cues, text="\n".join(cue[2] for cue in cues))


async def _resolve(client: AsyncClient, adapters: Adapters, video: ResolvedVideo) -> str:
    adapters.video_source.videos = {YOUTUBE_URL: video}  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def test_manual_track_is_preferred_over_automatic(
    client: AsyncClient, adapters: Adapters
) -> None:
    zh_auto = automatic("zh-Hans")
    en_manual = manual("en")
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(zh_auto, [(0.0, 1.0, "自动字幕内容")]),
        ("dQw4w9WgXcQ", "en"): payload(en_manual, [(0.0, 2.0, "manual english subtitle")]),
    }
    video_id = await _resolve(client, adapters, video_with(zh_auto, en_manual))

    response = await client.get(f"/api/videos/{video_id}/subtitles")

    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "en"
    assert body["source_type"] == "manual"
    assert body["text"] == "manual english subtitle"


@pytest.mark.parametrize(
    ("languages", "expected"),
    [
        (["en", "zh-Hans"], "zh-Hans"),
        (["en", "zh-CN"], "zh-CN"),
        (["ja", "en"], "en"),
        (["ko", "ja"], "ko"),
    ],
)
async def test_language_preference_order(
    client: AsyncClient,
    adapters: Adapters,
    languages: list[str],
    expected: str,
) -> None:
    tracks = [manual(language) for language in languages]
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", track.language): payload(track, [(0.0, 1.0, f"{track.language} text")])
        for track in tracks
    }
    video_id = await _resolve(client, adapters, video_with(*tracks))

    body = (await client.get(f"/api/videos/{video_id}/subtitles")).json()

    assert body["language"] == expected
    assert body["source_type"] == "manual"


async def test_automatic_track_is_used_when_only_automatic_exists(
    client: AsyncClient, adapters: Adapters
) -> None:
    zh_auto = automatic("zh-Hans")
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(zh_auto, [(0.0, 1.0, "自动生成")])
    }
    video_id = await _resolve(client, adapters, video_with(zh_auto))

    body = (await client.get(f"/api/videos/{video_id}/subtitles")).json()

    assert body["source_type"] == "auto"
    assert body["language"] == "zh-Hans"


async def test_resolving_without_subtitles_returns_409_with_chinese_message(
    client: AsyncClient, adapters: Adapters
) -> None:
    video_id = await _resolve(client, adapters, video_with())
    resolved = (await client.get(f"/api/videos/{video_id}")).json()
    assert resolved["can_analyze"] is False

    response = await client.get(f"/api/videos/{video_id}/subtitles")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "subtitles_unavailable"
    assert "字幕" in error["message"]
    assert error["details"]["video_id"] == video_id

    exported = await client.get(f"/api/videos/{video_id}/subtitles?format=srt")
    assert exported.status_code == 409
    assert exported.json()["error"]["code"] == "subtitles_unavailable"


async def test_can_analyze_follows_stored_subtitle(
    client: AsyncClient, adapters: Adapters
) -> None:
    track = manual("zh-Hans")
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(track, [(0.0, 1.0, "内容")])
    }
    video_id = await _resolve(client, adapters, video_with(track))

    assert (await client.get(f"/api/videos/{video_id}/subtitles")).json()["can_analyze"] is True
    assert (await client.get(f"/api/videos/{video_id}")).json()["can_analyze"] is True


async def test_subtitle_json_exposes_cues_and_plain_text(
    client: AsyncClient, adapters: Adapters
) -> None:
    track = manual("zh-Hans")
    cues = [(0.0, 2.5, "第一句"), (2.5, 65.25, "第二句")]
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(track, cues)
    }
    video_id = await _resolve(client, adapters, video_with(track))

    body = (await client.get(f"/api/videos/{video_id}/subtitles")).json()

    assert body == {
        "language": "zh-Hans",
        "source_type": "manual",
        "text": "第一句\n第二句",
        "cues": [
            {"start": 0.0, "end": 2.5, "text": "第一句"},
            {"start": 2.5, "end": 65.25, "text": "第二句"},
        ],
        "can_analyze": True,
    }


async def test_export_srt_has_subrip_mime_and_valid_timestamps(
    client: AsyncClient, adapters: Adapters
) -> None:
    track = manual("zh-Hans")
    cues = [(0.0, 2.5, "第一句"), (2.5, 65.25, LONG_TEXT)]
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(track, cues)
    }
    video_id = await _resolve(client, adapters, video_with(track))

    response = await client.get(f"/api/videos/{video_id}/subtitles?format=srt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-subrip")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert '.srt"' in disposition
    body = response.text
    assert "1\n00:00:00,000 --> 00:00:02,500\n第一句" in body
    assert "2\n00:00:02,500 --> 00:01:05,250\n" + LONG_TEXT in body
    timestamps = re.findall(r"\d{2}:\d{2}:\d{2},\d{3}", body)
    assert len(timestamps) == 4


async def test_export_vtt_has_webvtt_header_and_dot_timestamps(
    client: AsyncClient, adapters: Adapters
) -> None:
    track = manual("zh-Hans")
    cues = [(0.0, 2.5, "第一句"), (2.5, 65.25, LONG_TEXT)]
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(track, cues)
    }
    video_id = await _resolve(client, adapters, video_with(track))

    response = await client.get(f"/api/videos/{video_id}/subtitles?format=vtt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vtt")
    assert '.vtt"' in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in body
    assert "00:00:02.500 --> 00:01:05.250" in body
    assert LONG_TEXT in body


async def test_export_txt_matches_displayed_text(
    client: AsyncClient, adapters: Adapters
) -> None:
    track = manual("zh-Hans")
    cues = [(0.0, 2.5, "第一句"), (2.5, 65.25, LONG_TEXT)]
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(track, cues)
    }
    video_id = await _resolve(client, adapters, video_with(track))
    displayed = (await client.get(f"/api/videos/{video_id}/subtitles")).json()["text"]

    response = await client.get(f"/api/videos/{video_id}/subtitles?format=txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert '.txt"' in response.headers["content-disposition"]
    assert response.text == displayed
    assert LONG_TEXT in response.text


async def test_export_for_unknown_video_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/videos/nope/subtitles?format=srt")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "video_not_found"


async def test_repeated_resolve_keeps_one_selection_and_refreshes_changed_track(
    client: AsyncClient, adapters: Adapters
) -> None:
    zh = manual("zh-Hans")
    en = manual("en")
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(zh, [(0.0, 1.0, "中文内容")]),
        ("dQw4w9WgXcQ", "en"): payload(en, [(0.0, 1.0, "english content")]),
    }
    video_id = await _resolve(client, adapters, video_with(zh))
    await _resolve(client, adapters, video_with(zh))
    assert len(adapters.video_source.subtitle_calls) == 1  # type: ignore[attr-defined]

    await _resolve(client, adapters, video_with(en))

    body = (await client.get(f"/api/videos/{video_id}/subtitles")).json()
    assert body["language"] == "en"
    assert body["text"] == "english content"


async def test_foreign_key_integrity_error_is_not_swallowed(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    """Only the ``subtitles.video_id`` identity conflict is recoverable.

    A Subtitle whose Video row does not exist violates the foreign key instead; that
    IntegrityError must surface, not be mistaken for the concurrent-resolve race. This
    case is tested below the HTTP seam because no HTTP path can create an orphan Video.
    """
    track = manual("zh-Hans")
    adapters.video_source.subtitles = {  # type: ignore[attr-defined]
        ("dQw4w9WgXcQ", "zh-Hans"): payload(track, [(0.0, 1.0, "内容")]),
    }
    orphan = Video(
        id="orphan-video",
        platform="youtube",
        platform_video_id="orphan",
        title="孤儿视频",
        duration_seconds=1,
        webpage_url=YOUTUBE_URL,
    )

    async with app.state.sessionmaker() as session:
        with pytest.raises(IntegrityError):
            await subtitles.sync_selection(session, adapters.video_source, orphan, video_with(track))  # type: ignore[arg-type]
