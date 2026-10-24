"""Terms, abuse reports and DRM/members refusal acceptance tests.

All cases run through the in-process HTTP seam. DRM/members content is served by
``FakeVideoSource``; the Download guard is checked against a seeded Video row because
resolve (correctly) refuses to persist such content in the first place.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from app.container import Adapters
from app.modules.catalog.models import Video
from app.modules.media.models import Download
from app.modules.ops.models import Report
from app.ports import Clock
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.fakes import sample_video

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

DRM_PHRASE = "不提供绕过 DRM"
MEMBERS_PHRASE = "不提供绕过会员权限"


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _report_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        stmt = select(func.count()).select_from(Report)
        return int((await session.execute(stmt)).scalar_one())


async def _download_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        stmt = select(func.count()).select_from(Download)
        return int((await session.execute(stmt)).scalar_one())


async def test_report_is_stored_with_id_and_created_at(
    client: AsyncClient, app: FastAPI, adapters: Adapters
) -> None:
    response = await client.post(
        "/api/reports",
        json={
            "url": "https://www.youtube.com/watch?v=abuse123",
            "reason": "copyright",
            "contact": "rights@example.com",
            "details": "该链接传播未授权转载内容",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "received"
    assert len(body["id"]) == 32
    assert _parse(body["created_at"]) == adapters.clock.now()

    async with app.state.sessionmaker() as session:
        row = await session.get(Report, body["id"])
        assert row is not None
        assert row.status == "received"
        assert row.reason == "copyright"
        assert row.url == "https://www.youtube.com/watch?v=abuse123"
        assert row.contact == "rights@example.com"
        assert row.details == "该链接传播未授权转载内容"
        assert row.created_at is not None


async def test_report_accepts_only_a_reason(client: AsyncClient) -> None:
    response = await client.post("/api/reports", json={"reason": "other"})

    assert response.status_code == 201
    assert response.json()["status"] == "received"


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "not-a-real-reason"},
        {"reason": "copyright", "url": "ftp://example.com/file"},
        {"reason": "copyright", "url": "not a url"},
    ],
)
async def test_invalid_report_is_refused_with_chinese_copy(
    client: AsyncClient, app: FastAPI, payload: dict
) -> None:
    response = await client.post("/api/reports", json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "report_invalid"
    assert any("\u4e00" <= char <= "\u9fff" for char in error["message"])
    assert await _report_count(app) == 0


async def test_report_length_limits_are_enforced(client: AsyncClient, app: FastAPI) -> None:
    response = await client.post(
        "/api/reports",
        json={"reason": "other", "details": "长" * 2001},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert await _report_count(app) == 0


@pytest.mark.parametrize(
    ("flags", "code", "phrase"),
    [
        ({"is_drm": True}, "drm_protected", DRM_PHRASE),
        ({"is_members_only": True}, "members_only", MEMBERS_PHRASE),
    ],
)
async def test_resolve_refuses_drm_and_members_content_without_bypass(
    client: AsyncClient,
    adapters: Adapters,
    app: FastAPI,
    flags: dict[str, bool],
    code: str,
    phrase: str,
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: sample_video(**flags)}  # type: ignore[attr-defined]

    response = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == code
    assert phrase in error["message"]
    async with app.state.sessionmaker() as session:
        stmt = select(func.count()).select_from(Video)
        assert int((await session.execute(stmt)).scalar_one()) == 0


@pytest.mark.parametrize(
    ("flags", "code", "phrase"),
    [
        ({"is_drm": True}, "drm_protected", DRM_PHRASE),
        ({"is_members_only": True}, "members_only", MEMBERS_PHRASE),
    ],
)
async def test_download_refuses_stored_drm_and_members_content(
    client: AsyncClient,
    app: FastAPI,
    adapters: Adapters,
    flags: dict[str, bool],
    code: str,
    phrase: str,
) -> None:
    video_id = await _seed_protected_video(app, adapters.clock, **flags)

    response = await client.post(
        "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}
    )

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == code
    assert phrase in error["message"]
    assert await _download_count(app) == 0


async def test_retention_policy_is_visible_in_api_copy(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.video_source.videos = {YOUTUBE_URL: sample_video()}  # type: ignore[attr-defined]
    resolved = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
    assert resolved.status_code == 200
    body = resolved.json()
    assert "1 小时" in body["retention_notice"]

    created = await client.post(
        "/api/downloads",
        json={"video_id": body["video"]["id"], "format_id": "bestaudio"},
    )
    assert created.status_code == 202
    assert "1 小时" in created.json()["retention_notice"]


async def _seed_protected_video(
    app: FastAPI, clock: Clock, *, is_drm: bool = False, is_members_only: bool = False
) -> str:
    video = Video(
        id=uuid4().hex,
        platform="youtube",
        platform_video_id=uuid4().hex,
        title="受保护视频",
        duration_seconds=60,
        webpage_url="https://example.com/protected",
        formats_json=[
            {
                "format_id": "bestaudio",
                "label": "仅音频",
                "ext": "m4a",
                "resolution": "仅音频",
                "has_video": False,
                "has_audio": True,
            }
        ],
        formats_fetched_at=clock.now(),
        is_drm=is_drm,
        is_members_only=is_members_only,
    )
    async with app.state.sessionmaker() as session:
        session.add(video)
        await session.commit()
    return video.id


async def test_report_submissions_are_rate_limited_per_ip(client: AsyncClient) -> None:
    for _ in range(5):
        accepted = await client.post("/api/reports", json={"reason": "other"})
        assert accepted.status_code == 201, accepted.text

    rejected = await client.post("/api/reports", json={"reason": "other"})
    assert rejected.status_code == 429, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "too_many_requests"
    assert error["details"]["scope"] == "reports.create"
    assert rejected.headers["retry-after"] == str(error["details"]["retry_after"])
