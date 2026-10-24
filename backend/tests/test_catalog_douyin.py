"""Douyin parsing behind the feature switch, exercised at the pre-agreed seams.

URL normalisation (pure) plus the in-process HTTP resolve/download/analysis chain
with ``FakeVideoSource``: no test ever contacts real Douyin.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.container import Adapters
from app.errors import AppError
from app.main import create_app
from app.modules.catalog.models import Video
from app.modules.catalog.urls import normalize_video_url
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.fakes import make_fake_adapters, sample_video

DOUYIN_SHARE_URL = "https://www.douyin.com/video/7123456789012345678"
DOUYIN_SHORT_URL = "https://v.douyin.com/AbC123"
YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

DOUYIN_ENABLED: frozenset[str] = frozenset({"youtube", "bilibili", "douyin"})


@asynccontextmanager
async def douyin_enabled_client(
    tmp_path: Path,
    **overrides: object,
) -> AsyncIterator[tuple[AsyncClient, Adapters, FastAPI]]:
    """Full-stack client with the Douyin switch on, mirroring the ``client`` fixture."""
    settings = Settings(
        _env_file=None,
        env="test",
        secret_key="test-only-secret",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'douyin.db').as_posix()}",
        data_dir=tmp_path / "data",
        log_level="WARNING",
        douyin_enabled=True,
        **overrides,  # type: ignore[arg-type]
    )
    adapters = make_fake_adapters()
    app = create_app(settings=settings, adapters=adapters)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, adapters, app


async def _video_row_count(app: FastAPI, platform: str, platform_video_id: str) -> int:
    async with app.state.sessionmaker() as session:
        stmt = (
            select(func.count())
            .select_from(Video)
            .where(Video.platform == platform, Video.platform_video_id == platform_video_id)
        )
        return int((await session.execute(stmt)).scalar_one())


@pytest.mark.parametrize(
    "raw",
    [
        DOUYIN_SHARE_URL,
        "https://m.douyin.com/video/7123456789012345678?share_douyin_app=h5",
        "https://v.douyin.com/AbC123/",
    ],
)
def test_douyin_urls_are_rejected_with_a_dedicated_code_when_the_switch_is_off(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw)

    assert raised.value.status == 422
    assert raised.value.code == "platform_not_enabled"
    assert raised.value.message == "抖音暂未开放"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (DOUYIN_SHARE_URL, DOUYIN_SHARE_URL),
        ("https://douyin.com/video/7123456789012345678", DOUYIN_SHARE_URL),
        (
            "https://www.douyin.com/video/7123456789012345678/?share_link_type=video_misc&tid=9",
            DOUYIN_SHARE_URL,
        ),
        (
            "https://m.douyin.com/video/7123456789012345678#fragment",
            DOUYIN_SHARE_URL,
        ),
        # Short links are forwarded as-is: only the adapter can follow the redirect.
        ("https://v.douyin.com/AbC123/?share_source=copy_system", DOUYIN_SHORT_URL),
    ],
)
def test_douyin_urls_normalise_when_the_switch_is_on(raw: str, expected: str) -> None:
    assert normalize_video_url(raw, enabled_platforms=DOUYIN_ENABLED) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.douyin.com/user/msomewhere",
        "https://www.douyin.com/discover",
        "https://live.douyin.com/123456",
        "https://www.douyin.com/video/not-a-number",
        "https://www.douyin.com/video/123456789012345678901234",
    ],
)
def test_non_video_douyin_pages_stay_unsupported(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw, enabled_platforms=DOUYIN_ENABLED)

    assert raised.value.code == "unsupported_url"


def test_douyin_switch_defaults_to_off_and_follows_the_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings(_env_file=None).douyin_enabled is False

    monkeypatch.setenv("APP_DOUYIN_ENABLED", "true")
    assert Settings(_env_file=None).douyin_enabled is True


async def test_resolve_endpoint_rejects_douyin_when_the_switch_is_off(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/videos/resolve", json={"url": DOUYIN_SHARE_URL})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "platform_not_enabled"
    assert error["message"] == "抖音暂未开放"
    assert error["code"] != "unsupported_url"


async def test_douyin_video_page_resolves_with_cover_and_single_watermarked_format(
    tmp_path: Path,
) -> None:
    async with douyin_enabled_client(tmp_path) as (client, _adapters, _app):
        response = await client.post("/api/videos/resolve", json={"url": DOUYIN_SHARE_URL})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["video"]["platform"] == "douyin"
    assert body["video"]["platform_video_id"] == "7123456789012345678"
    assert body["video"]["title"]
    assert body["video"]["thumbnail_url"]
    assert body["video"]["duration_seconds"] > 0
    assert len(body["formats"]) == 1
    assert "水印" in body["formats"][0]["label"]


async def test_douyin_short_link_and_share_page_share_one_video_identity(
    tmp_path: Path,
) -> None:
    async with douyin_enabled_client(tmp_path) as (client, _adapters, app):
        from_short = await client.post("/api/videos/resolve", json={"url": DOUYIN_SHORT_URL})
        from_page = await client.post("/api/videos/resolve", json={"url": DOUYIN_SHARE_URL})

    assert from_short.status_code == 200, from_short.text
    assert from_page.status_code == 200, from_page.text
    assert from_short.json()["video"]["id"] == from_page.json()["video"]["id"]
    assert await _video_row_count(app, "douyin", "7123456789012345678") == 1


async def test_bilibili_and_youtube_resolve_unchanged_when_douyin_is_enabled(
    tmp_path: Path,
) -> None:
    async with douyin_enabled_client(tmp_path) as (client, adapters, _app):
        adapters.video_source.videos = {  # type: ignore[attr-defined]
            YOUTUBE_URL: sample_video(),
            "https://www.bilibili.com/video/BV1xx411c7mD": sample_video(
                platform="bilibili", platform_video_id="BV1xx411c7mD"
            ),
        }
        youtube = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})
        bilibili = await client.post(
            "/api/videos/resolve", json={"url": "https://www.bilibili.com/video/BV1xx411c7mD"}
        )

    assert youtube.status_code == 200, youtube.text
    assert youtube.json()["video"]["platform"] == "youtube"
    assert bilibili.status_code == 200, bilibili.text
    assert bilibili.json()["video"]["platform"] == "bilibili"
