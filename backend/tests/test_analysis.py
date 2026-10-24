"""Analysis acceptance tests through the in-process HTTP seam.

The Summarizer is scripted per test (deltas, marker, errors, hangs); Quota uses the
FrozenClock so Asia/Shanghai day rollover is deterministic. Generation runs as a
background asyncio task, so tests poll the detail endpoint until a terminal status.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any

import httpx
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from app.modules.catalog.models import Video
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient

from tests.fakes import FakeSummarizer, make_fake_adapters, sample_video

PASSWORD = "correct-horse"
TERMINAL = {"completed", "failed"}

SCRIPT = [
    "## 核心要点\n",
    "- 背景介绍\n",
    "- 最终结论\n",
    "## 思维导图\n",
    "- 主题\n",
    "  - 子主题\n",
]
EXPECTED_SUMMARY = "## 核心要点\n- 背景介绍\n- 最终结论"
EXPECTED_MINDMAP = "- 主题\n  - 子主题"


def _url(platform_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={platform_video_id}"


async def _register(client: AsyncClient, email: str = "learner@example.com") -> dict[str, str]:
    response = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _login(client: AsyncClient, email: str = "learner@example.com") -> dict[str, str]:
    response = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _resolve(
    client: AsyncClient,
    adapters: Adapters,
    platform_video_id: str = "mainvideo01",
    *,
    subtitles: bool = True,
) -> str:
    url = _url(platform_video_id)
    video = sample_video(platform_video_id=platform_video_id)
    if not subtitles:
        video = dataclasses.replace(video, subtitles=())
    adapters.video_source.videos[url] = video  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _create(
    client: AsyncClient,
    headers: dict[str, str],
    video_id: str,
    *,
    force: bool = False,
) -> httpx.Response:
    return await client.post(
        "/api/analyses", json={"video_id": video_id, "force": force}, headers=headers
    )


async def _me(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/api/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["quota"]


async def _get(
    client: AsyncClient, headers: dict[str, str], analysis_id: str
) -> dict[str, Any]:
    response = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _wait_terminal(
    client: AsyncClient,
    headers: dict[str, str],
    analysis_id: str,
    *,
    limit_seconds: float = 5.0,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_seconds
    while loop.time() < deadline:
        body = await _get(client, headers, analysis_id)
        if body["status"] in TERMINAL:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"analysis {analysis_id} did not reach a terminal status")


def _parse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


async def _stream(
    client: AsyncClient, headers: dict[str, str], analysis_id: str
) -> tuple[httpx.Response, list[tuple[str, dict[str, Any]]]]:
    response = await client.get(f"/api/analyses/{analysis_id}/stream", headers=headers)
    assert response.status_code == 200, response.text
    return response, _parse_events(response.text)


async def test_stream_events_in_order_and_result_is_persisted(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)

    created = await _create(client, headers, video_id)
    assert created.status_code == 201, created.text
    body = created.json()
    analysis_id = body["id"]
    assert body["video_id"] == video_id
    assert body["status"] in {"pending", "streaming", "completed"}

    detail = await _wait_terminal(client, headers, analysis_id)
    assert detail["status"] == "completed"
    assert detail["summary_markdown"] == EXPECTED_SUMMARY
    assert detail["mindmap_markdown"] == EXPECTED_MINDMAP
    assert detail["subtitle_source"] == "manual"
    assert detail["truncated"] is False
    assert detail["error"] is None

    response, events = await _stream(client, headers, analysis_id)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-2:] == ["mindmap", "done"]
    assert names[1:-2] and set(names[1:-2]) == {"delta"}

    meta = events[0][1]
    assert meta["analysis_id"] == analysis_id
    assert meta["subtitle_source"] == "manual"
    assert "".join(payload["text"] for name, payload in events if name == "delta") == (
        EXPECTED_SUMMARY
    )
    assert events[-2][1]["markdown"] == EXPECTED_MINDMAP

    # The prompt is built from the Subtitle text and asks for the mindmap marker.
    prompts = adapters.summarizer.prompts  # type: ignore[attr-defined]
    assert "示例字幕" in prompts[-1]
    assert "人工" in prompts[-1]
    assert "## 思维导图" in prompts[-1]


async def test_stream_replays_persisted_result_for_reconnecting_clients(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "replayvid01")
    analysis_id = (await _create(client, headers, video_id)).json()["id"]
    await _wait_terminal(client, headers, analysis_id)

    _, first = await _stream(client, headers, analysis_id)
    _, second = await _stream(client, headers, analysis_id)

    assert second == first
    assert [name for name, _ in second] == ["meta", "delta", "mindmap", "done"]


async def test_partial_summary_is_persisted_while_streaming(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    adapters.summarizer.delay_seconds = 0.05  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "partialvid1")
    analysis_id = (await _create(client, headers, video_id)).json()["id"]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    partial = ""
    while loop.time() < deadline:
        body = await _get(client, headers, analysis_id)
        if body["summary_markdown"]:
            partial = body["summary_markdown"]
            if body["status"] == "streaming":
                break
        if body["status"] in TERMINAL:
            break
        await asyncio.sleep(0.01)

    assert partial
    assert EXPECTED_SUMMARY.startswith(partial)

    detail = await _wait_terminal(client, headers, analysis_id)
    assert detail["summary_markdown"] == EXPECTED_SUMMARY


async def test_fourth_analysis_is_rejected_with_reset_time_then_resets_next_day(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)
    for index in range(3):
        video_id = await _resolve(client, adapters, f"quotavid00{index + 1}")
        if index:
            # #12: one new Analysis per Account per 10 seconds.
            adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]
        created = await _create(client, headers, video_id)
        assert created.status_code == 201, created.text
        await _wait_terminal(client, headers, created.json()["id"])

    quota = await _me(client, headers)
    assert (quota["used"], quota["remaining"]) == (3, 0)

    fourth_video = await _resolve(client, adapters, "quotavid004")
    adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]
    rejected = await _create(client, headers, fourth_video)
    assert rejected.status_code == 429
    error = rejected.json()["error"]
    assert error["code"] == "quota_exhausted"
    assert error["details"]["remaining"] == 0
    assert error["details"]["daily_limit"] == 3
    assert error["details"]["resets_at"] == "2026-01-16T00:00:00+08:00"

    # Crossing the Asia/Shanghai midnight resets the daily Quota.
    adapters.clock.advance(days=1)  # type: ignore[attr-defined]
    headers = await _login(client)
    allowed = await _create(client, headers, fourth_video)
    assert allowed.status_code == 201, allowed.text
    await _wait_terminal(client, headers, allowed.json()["id"])
    assert (await _me(client, headers))["used"] == 1


async def test_failure_releases_quota_and_allows_retry(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.error = RuntimeError("upstream exploded")  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)

    created = await _create(client, headers, video_id)
    assert created.status_code == 201
    analysis_id = created.json()["id"]

    detail = await _wait_terminal(client, headers, analysis_id)
    assert detail["status"] == "failed"
    assert detail["error"]["code"] == "analysis_failed"
    assert detail["error"]["message"]
    assert detail["summary_markdown"] == ""
    assert (await _me(client, headers))["used"] == 0

    failure_events = await _stream(client, headers, analysis_id)
    names = [name for name, _ in failure_events[1]]
    assert names == ["meta", "error"]
    assert failure_events[1][-1][1]["code"] == "analysis_failed"

    adapters.summarizer.error = None  # type: ignore[attr-defined]
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]  # creation throttle
    retried = await _create(client, headers, video_id)
    assert retried.status_code == 201
    assert retried.json()["id"] != analysis_id
    await _wait_terminal(client, headers, retried.json()["id"])
    assert (await _me(client, headers))["used"] == 1


async def test_duplicate_clicks_reuse_the_in_progress_analysis_and_reserve_once(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    adapters.summarizer.delay_seconds = 0.05  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)

    first = await _create(client, headers, video_id)
    second = await _create(client, headers, video_id)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert (await _me(client, headers))["used"] == 1

    await _wait_terminal(client, headers, first.json()["id"])
    third = await _create(client, headers, video_id)
    assert third.status_code == 200
    assert third.json()["id"] == first.json()["id"]
    assert (await _me(client, headers))["used"] == 1


async def test_concurrent_creates_reserve_only_once(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    adapters.summarizer.delay_seconds = 0.05  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)

    responses = await asyncio.gather(
        _create(client, headers, video_id), _create(client, headers, video_id)
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 201], [response.text for response in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert (await _me(client, headers))["used"] == 1
    await _wait_terminal(client, headers, responses[0].json()["id"])


async def test_no_subtitle_is_rejected_before_reserving_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "nosubvid001", subtitles=False)

    rejected = await _create(client, headers, video_id)

    assert rejected.status_code == 409
    error = rejected.json()["error"]
    assert error["code"] == "subtitles_unavailable"
    assert "字幕" in error["message"]
    assert (await _me(client, headers))["used"] == 0


async def test_drm_and_members_only_videos_are_rejected(
    client: AsyncClient, app: FastAPI
) -> None:
    async with app.state.sessionmaker() as session:
        drm = Video(
            platform="youtube",
            platform_video_id="drm-video",
            title="DRM",
            duration_seconds=10,
            webpage_url="https://example.com/drm",
            is_drm=True,
            formats_json=[],
            subtitles_json=[],
        )
        members = Video(
            platform="youtube",
            platform_video_id="members-video",
            title="Members",
            duration_seconds=10,
            webpage_url="https://example.com/members",
            is_members_only=True,
            formats_json=[],
            subtitles_json=[],
        )
        session.add_all([drm, members])
        await session.commit()
        drm_id, members_id = drm.id, members.id

    headers = await _register(client)
    drm_response = await _create(client, headers, drm_id)
    members_response = await _create(client, headers, members_id)

    assert drm_response.status_code == 403
    assert drm_response.json()["error"]["code"] == "drm_protected"
    assert members_response.status_code == 403
    assert members_response.json()["error"]["code"] == "members_only"
    assert (await _me(client, headers))["used"] == 0


async def test_ownership_is_enforced_for_detail_and_stream(
    client: AsyncClient, adapters: Adapters
) -> None:
    owner = await _register(client, "owner@example.com")
    other = await _register(client, "other@example.com")
    video_id = await _resolve(client, adapters)
    analysis_id = (await _create(client, owner, video_id)).json()["id"]
    await _wait_terminal(client, owner, analysis_id)

    detail = await client.get(f"/api/analyses/{analysis_id}", headers=other)
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "analysis_not_found"

    stream = await client.get(f"/api/analyses/{analysis_id}/stream", headers=other)
    assert stream.status_code == 404
    assert stream.json()["error"]["code"] == "analysis_not_found"

    anonymous = await client.get(f"/api/analyses/{analysis_id}")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "auth_required"

    # The owner still sees it.
    assert (await _get(client, owner, analysis_id))["status"] == "completed"


async def test_viewing_existing_result_never_consumes_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)
    video_id = await _resolve(client, adapters)
    analysis_id = (await _create(client, headers, video_id)).json()["id"]
    await _wait_terminal(client, headers, analysis_id)

    for _ in range(3):
        await _get(client, headers, analysis_id)
    await _stream(client, headers, analysis_id)

    reused = await _create(client, headers, video_id)
    assert reused.status_code == 200
    assert reused.json()["id"] == analysis_id
    assert (await _me(client, headers))["used"] == 1


async def test_force_creates_a_new_analysis_and_consumes_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)
    first_id = (await _create(client, headers, video_id)).json()["id"]
    await _wait_terminal(client, headers, first_id)

    adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]  # creation throttle
    forced = await _create(client, headers, video_id, force=True)
    assert forced.status_code == 201
    assert forced.json()["id"] != first_id
    await _wait_terminal(client, headers, forced.json()["id"])
    assert (await _me(client, headers))["used"] == 2


async def test_me_reports_quota_with_reset_time(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)

    fresh = await _me(client, headers)
    assert fresh == {
        "daily_limit": 3,
        "used": 0,
        "remaining": 3,
        "resets_at": "2026-01-16T00:00:00+08:00",
        "membership": "free",
    }

    video_id = await _resolve(client, adapters)
    analysis_id = (await _create(client, headers, video_id)).json()["id"]
    await _wait_terminal(client, headers, analysis_id)

    used = await _me(client, headers)
    assert (used["used"], used["remaining"]) == (1, 2)


async def test_analysis_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/analyses", json={"video_id": "whatever"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


async def test_generation_timeout_marks_failed_and_releases_quota(settings: Settings) -> None:
    custom = settings.model_copy(update={"analysis_timeout_seconds": 0.05})
    summarizer = FakeSummarizer(chunks=list(SCRIPT), hang_seconds=5.0)
    custom_adapters = make_fake_adapters(summarizer=summarizer)
    app = create_app(settings=custom, adapters=custom_adapters)

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as scoped:
            headers = await _register(scoped, "timeout@example.com")
            video_id = await _resolve(scoped, custom_adapters, "timeoutvid1")
            created = await _create(scoped, headers, video_id)
            assert created.status_code == 201

            detail = await _wait_terminal(scoped, headers, created.json()["id"])
            assert detail["status"] == "failed"
            assert detail["error"]["code"] == "analysis_failed"
            assert (await _me(scoped, headers))["used"] == 0


async def test_analysis_detail_reports_unknown_id(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(client)
    response = await client.get("/api/analyses/nope", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


async def test_create_rejects_unknown_video(client: AsyncClient) -> None:
    headers = await _register(client)
    response = await _create(client, headers, "does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "video_not_found"
