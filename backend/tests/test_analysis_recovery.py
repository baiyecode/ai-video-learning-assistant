"""Analysis lifecycle hardening: restart recovery and immutable Subtitle snapshots.

Both cases go through the real composition root. The restart test closes one
lifespan and starts a second app on the same database, which is what a process
restart looks like to the rows left behind.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from app.modules.analysis.models import ACTIVE_STATUSES, Analysis, AnalysisStatus
from app.modules.catalog.models import Subtitle
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from tests.fakes import FakeSummarizer, make_fake_adapters, sample_video

PASSWORD = "correct-horse"


def _url(key: str) -> str:
    return f"https://www.youtube.com/watch?v={key}"


@asynccontextmanager
async def _running(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _register(client: AsyncClient) -> tuple[dict[str, str], str]:
    response = await client.post(
        "/api/auth/register", json={"email": "restart@example.com", "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["account"]["id"]


async def _resolve(client: AsyncClient, adapters: Adapters, key: str) -> str:
    url = _url(key)
    adapters.video_source.videos[url] = sample_video(platform_video_id=key)  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _detail(client: AsyncClient, headers: dict[str, str], analysis_id: str) -> dict:
    response = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _wait_status(
    client: AsyncClient,
    headers: dict[str, str],
    analysis_id: str,
    expected: set[str],
) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        body = await _detail(client, headers, analysis_id)
        if body["status"] in expected:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"analysis {analysis_id} never reached {expected}")


async def test_restart_marks_interrupted_analysis_failed_and_releases_quota(
    settings: Settings,
) -> None:
    slow = FakeSummarizer(delay_seconds=30.0)
    adapters = make_fake_adapters(summarizer=slow)
    app = create_app(settings=settings, adapters=adapters)
    async with _running(app) as client:
        headers, _account_id = await _register(client)
        video_id = await _resolve(client, adapters, "restart0001")
        created = await client.post(
            "/api/analyses", json={"video_id": video_id}, headers=headers
        )
        assert created.status_code == 201, created.text
        analysis_id = created.json()["id"]
        await _wait_status(client, headers, analysis_id, {"pending", "streaming"})

    # ``LifespanManager`` exit cancels the generation task; the row stays active
    # until the next process starts.
    adapters_after = make_fake_adapters()
    restarted = create_app(settings=settings, adapters=adapters_after)
    async with _running(restarted) as client:
        quota = await client.get("/api/me", headers=headers)
        assert quota.status_code == 200, quota.text
        assert quota.json()["quota"]["used"] == 0
        assert quota.json()["quota"]["remaining"] == 3

        detail = await _detail(client, headers, analysis_id)
        assert detail["status"] == "failed"
        assert detail["error"]["code"] == "analysis_failed"
        assert any("\u4e00" <= char <= "\u9fff" for char in detail["error"]["message"])

        # The failed row no longer holds the active slot or a Quota unit.
        retry = await client.post(
            "/api/analyses", json={"video_id": video_id}, headers=headers
        )
        assert retry.status_code == 201, retry.text
        assert retry.json()["id"] != analysis_id
        finished = await _wait_status(
            client, headers, retry.json()["id"], {"completed", "failed"}
        )
        assert finished["status"] == "completed"


async def test_generation_reads_the_snapshot_not_the_mutable_subtitle(
    client: AsyncClient, adapters: Adapters, app: FastAPI
) -> None:
    headers, account_id = await _register(client)
    video_id = await _resolve(client, adapters, "snapshot001")

    async with app.state.sessionmaker() as session:
        stored = await session.scalar(select(Subtitle).where(Subtitle.video_id == video_id))
        assert stored is not None
        assert stored.text == "示例字幕"

        analysis = Analysis(
            account_id=account_id,
            video_id=video_id,
            subtitle_id=stored.id,
            status=AnalysisStatus.PENDING.value,
            summary_markdown="",
            mindmap_markdown="",
            subtitle_source="manual",
            subtitle_language="zh-Hans",
            subtitle_text="快照字幕内容",
            subtitle_cues=[{"start": 0.0, "end": 2.0, "text": "快照字幕内容"}],
            created_at=adapters.clock.now(),
            updated_at=adapters.clock.now(),
        )
        session.add(analysis)
        await session.commit()
        analysis_id = analysis.id

    app.state.analysis_manager.submit(analysis_id)
    detail = await _wait_status(client, headers, analysis_id, {"completed", "failed"})

    assert detail["status"] == "completed", detail
    prompt = adapters.summarizer.prompts[0]  # type: ignore[attr-defined]
    assert "快照字幕内容" in prompt
    assert "示例字幕" not in prompt


async def test_no_active_rows_remain_after_recovery(
    settings: Settings,
) -> None:
    """Recovery is idempotent: a second restart finds nothing to settle."""
    adapters = make_fake_adapters(summarizer=FakeSummarizer(delay_seconds=30.0))
    app = create_app(settings=settings, adapters=adapters)
    async with _running(app) as client:
        headers, _account_id = await _register(client)
        video_id = await _resolve(client, adapters, "restart0002")
        created = await client.post(
            "/api/analyses", json={"video_id": video_id}, headers=headers
        )
        assert created.status_code == 201, created.text
        await _wait_status(client, headers, created.json()["id"], {"pending", "streaming"})

    for _ in range(2):
        restarted = create_app(settings=settings, adapters=make_fake_adapters())
        async with _running(restarted):
            pass

    check = create_app(settings=settings, adapters=make_fake_adapters())
    async with _running(check) as client:
        quota = await client.get("/api/me", headers=headers)
        assert quota.json()["quota"]["remaining"] == 3
        async with check.state.sessionmaker() as session:
            active = (
                await session.scalars(
                    select(Analysis).where(Analysis.status.in_(ACTIVE_STATUSES))
                )
            ).all()
        assert active == []
