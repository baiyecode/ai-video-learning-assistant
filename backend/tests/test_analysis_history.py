"""History and re-analysis acceptance tests through the in-process HTTP seam.

Covers ``GET /api/analyses`` (own rows only, newest first), Quota-free revisits,
explicit re-analysis with ``force`` (new row, exactly one Quota unit, previous result
frozen) and isolation between Accounts. No real network: the Summarizer is scripted.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from app.container import Adapters
from httpx import AsyncClient

from tests.fakes import sample_video

PASSWORD = "correct-horse"
TERMINAL = {"completed", "failed"}

OLD_SUMMARY = "## 旧要点\n- 旧结论"
OLD_MINDMAP = "- 旧主题"
NEW_SUMMARY = "## 新要点\n- 新结论"
NEW_MINDMAP = "- 新主题"

LIST_SUMMARY = "## 核心要点\n- 背景介绍\n- 最终结论"
SCRIPT_FOR_LIST = [LIST_SUMMARY, "\n## 思维导图\n", "- 主题"]

OLD_SCRIPT = [OLD_SUMMARY, "\n## 思维导图\n", OLD_MINDMAP]
NEW_SCRIPT = [NEW_SUMMARY, "\n## 思维导图\n", NEW_MINDMAP]


def _url(platform_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={platform_video_id}"


async def _register(client: AsyncClient, email: str = "learner@example.com") -> dict[str, str]:
    response = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _resolve(
    client: AsyncClient,
    adapters: Adapters,
    platform_video_id: str = "historyvid1",
    *,
    title: str = "示例视频",
) -> str:
    url = _url(platform_video_id)
    adapters.video_source.videos[url] = sample_video(  # type: ignore[attr-defined]
        platform_video_id=platform_video_id, title=title
    )
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


async def _get(client: AsyncClient, headers: dict[str, str], analysis_id: str) -> dict[str, Any]:
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


async def _list(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get("/api/analyses", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return body


async def _spend_all_quota(
    client: AsyncClient, adapters: Adapters, headers: dict[str, str]
) -> list[str]:
    ids: list[str] = []
    for index in range(3):
        video_id = await _resolve(client, adapters, f"exhaustvid{index + 1}")
        created = await _create(client, headers, video_id)
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
        await _wait_terminal(client, headers, created.json()["id"])
    return ids


async def test_list_shows_only_own_analyses_newest_first_with_video_and_snippet(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT_FOR_LIST)  # type: ignore[attr-defined]
    headers = await _register(client)
    first_video = await _resolve(client, adapters, "listvid0001", title="第一个视频")
    first_id = (await _create(client, headers, first_video)).json()["id"]
    await _wait_terminal(client, headers, first_id)

    adapters.clock.advance(seconds=60)  # type: ignore[attr-defined]
    second_video = await _resolve(client, adapters, "listvid0002", title="第二个视频")
    second_id = (await _create(client, headers, second_video)).json()["id"]
    await _wait_terminal(client, headers, second_id)

    items = await _list(client, headers)

    assert [item["id"] for item in items] == [second_id, first_id]
    newest = items[0]
    assert newest["video_id"] == second_video
    assert newest["status"] == "completed"
    assert newest["subtitle_source"] == "manual"
    assert newest["truncated"] is False
    assert newest["created_at"]
    assert newest["completed_at"]
    assert newest["error_code"] is None
    assert "背景介绍" in newest["summary_snippet"]
    assert len(newest["summary_snippet"]) <= 120
    assert newest["video"]["title"] == "第二个视频"
    assert newest["video"]["platform"] == "youtube"
    assert newest["video"]["thumbnail_url"] is None
    assert items[1]["video"]["title"] == "第一个视频"


async def test_list_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/analyses")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


async def test_list_never_leaks_another_accounts_analysis(
    client: AsyncClient, adapters: Adapters
) -> None:
    owner = await _register(client, "owner@example.com")
    other = await _register(client, "other@example.com")
    video_id = await _resolve(client, adapters)
    analysis_id = (await _create(client, owner, video_id)).json()["id"]
    await _wait_terminal(client, owner, analysis_id)

    assert await _list(client, other) == []

    guessed = [item for item in await _list(client, other) if item["id"] == analysis_id]
    assert guessed == []
    detail = await client.get(f"/api/analyses/{analysis_id}", headers=other)
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "analysis_not_found"


async def test_list_detail_and_stream_visits_do_not_consume_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SCRIPT_FOR_LIST)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)
    analysis_id = (await _create(client, headers, video_id)).json()["id"]
    await _wait_terminal(client, headers, analysis_id)
    assert (await _me(client, headers))["used"] == 1

    await _list(client, headers)
    await _list(client, headers)
    await _get(client, headers, analysis_id)
    stream = await client.get(f"/api/analyses/{analysis_id}/stream", headers=headers)
    assert stream.status_code == 200

    assert (await _me(client, headers))["used"] == 1


async def test_force_creates_new_row_consumes_exactly_one_and_keeps_previous_result(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(OLD_SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)
    first_id = (await _create(client, headers, video_id)).json()["id"]
    first = await _wait_terminal(client, headers, first_id)
    assert first["summary_markdown"] == OLD_SUMMARY

    adapters.summarizer.chunks = list(NEW_SCRIPT)  # type: ignore[attr-defined]
    adapters.clock.advance(seconds=60)  # type: ignore[attr-defined]
    forced = await _create(client, headers, video_id, force=True)
    assert forced.status_code == 201, forced.text
    second_id = forced.json()["id"]
    assert second_id != first_id

    second = await _wait_terminal(client, headers, second_id)
    assert second["summary_markdown"] == NEW_SUMMARY
    assert second["mindmap_markdown"] == NEW_MINDMAP
    assert (await _me(client, headers))["used"] == 2

    # The previous Analysis and its snapshot survive untouched.
    previous = await _get(client, headers, first_id)
    assert previous["summary_markdown"] == OLD_SUMMARY
    assert previous["mindmap_markdown"] == OLD_MINDMAP
    assert previous["created_at"] == first["created_at"]
    assert previous["subtitle_source"] == "manual"

    items = await _list(client, headers)
    assert [item["id"] for item in items] == [second_id, first_id]


async def test_force_with_exhausted_quota_is_rejected_and_keeps_previous_result(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(OLD_SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    analysis_ids = await _spend_all_quota(client, adapters, headers)
    assert (await _me(client, headers))["remaining"] == 0

    first_video = (await _list(client, headers))[-1]["video_id"]
    rejected = await _create(client, headers, first_video, force=True)

    assert rejected.status_code == 429
    error = rejected.json()["error"]
    assert error["code"] == "quota_exhausted"
    assert error["details"]["remaining"] == 0
    assert error["details"]["resets_at"] == "2026-01-16T00:00:00+08:00"

    # No new Analysis row: the history is unchanged.
    items = await _list(client, headers)
    assert sorted(item["id"] for item in items) == sorted(analysis_ids)
    assert (await _me(client, headers))["used"] == 3
    assert (await _get(client, headers, analysis_ids[0]))["summary_markdown"] == OLD_SUMMARY


async def test_force_while_analysis_is_in_progress_reuses_it_without_spending_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(OLD_SCRIPT)  # type: ignore[attr-defined]
    adapters.summarizer.delay_seconds = 0.05  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)
    first = await _create(client, headers, video_id)
    assert first.status_code == 201

    forced = await _create(client, headers, video_id, force=True)

    assert forced.status_code == 200
    assert forced.json()["id"] == first.json()["id"]
    assert (await _me(client, headers))["used"] == 1
    await _wait_terminal(client, headers, first.json()["id"])


async def test_failed_analysis_reports_error_code_in_history(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.error = RuntimeError("upstream exploded")  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters)
    analysis_id = (await _create(client, headers, video_id)).json()["id"]
    await _wait_terminal(client, headers, analysis_id)

    items = await _list(client, headers)

    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["error_code"] == "analysis_failed"
    assert items[0]["summary_snippet"] == ""
    assert items[0]["completed_at"]
