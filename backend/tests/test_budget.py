"""AI budget acceptance tests: daily spend gate, recording and read availability.

The budget ledger is injected through the adapter container (``FakeBudgetLedger``),
so these tests never touch DeepSeek. A rejection must happen *before* Quota is
reserved, while viewing finished Analyses stays available.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx
from app.adapters.db_budget import DbBudgetLedger
from app.config import Settings
from app.container import Adapters
from app.db import create_engine_and_sessionmaker, init_db
from app.main import create_app
from app.ports import SubtitlePayload
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient

from tests.fakes import (
    FakeBudgetLedger,
    FakeSummarizer,
    FrozenClock,
    make_fake_adapters,
    sample_subtitle_track,
    sample_video,
)

PASSWORD = "correct-horse"
SUMMARY_SCRIPT = [
    "## 核心要点\n",
    "- 背景\n",
    "## 思维导图\n",
    "- 主题\n",
]


def _url(key: str) -> str:
    return f"https://www.youtube.com/watch?v={key}"


async def _register(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register", json={"email": "budget@example.com", "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _resolve(client: AsyncClient, adapters: Adapters, key: str) -> str:
    url = _url(key)
    adapters.video_source.videos[url] = sample_video(platform_video_id=key)  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _quota(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/api/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["quota"]


async def _wait_terminal(
    client: AsyncClient, headers: dict[str, str], analysis_id: str
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        response = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
        body = response.json()
        if body["status"] in {"completed", "failed"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("analysis did not finish")


def _client_for(
    settings: Settings, adapters: Adapters
) -> tuple[FastAPI, httpx.ASGITransport]:
    app = create_app(settings=settings, adapters=adapters)
    return app, httpx.ASGITransport(app=app, raise_app_exceptions=False)


async def test_new_analysis_is_blocked_when_the_daily_budget_is_exhausted(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.budget_ledger.spent_usd = 1.0  # type: ignore[attr-defined]
    adapters.budget_ledger.budget_usd = 1.0  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "budgetvid01")

    rejected = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)

    assert rejected.status_code == 429, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "budget_exhausted"
    assert "预算" in error["message"]
    assert "2026-01-16" in error["message"] or "00:00" in error["message"]
    assert error["details"]["resets_at"] == "2026-01-16T00:00:00+08:00"
    # The budget gate runs before Quota reservation.
    quota = await _quota(client, headers)
    assert (quota["used"], quota["remaining"]) == (0, 3)


async def test_existing_results_remain_viewable_when_the_budget_is_exhausted(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SUMMARY_SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "budgetvid02")
    created = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert created.status_code == 201, created.text
    analysis_id = created.json()["id"]
    detail = await _wait_terminal(client, headers, analysis_id)
    assert detail["status"] == "completed"

    adapters.budget_ledger.spent_usd = 10.0  # type: ignore[attr-defined]
    adapters.budget_ledger.budget_usd = 10.0  # type: ignore[attr-defined]

    # Detail and SSE replay never consult the budget.
    replayed = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
    assert replayed.status_code == 200
    assert replayed.json()["summary_markdown"]

    stream = await client.get(f"/api/analyses/{analysis_id}/stream", headers=headers)
    assert stream.status_code == 200
    assert "event: done" in stream.text

    # A genuinely new Analysis on another Video is still refused.
    adapters.clock.advance(seconds=10)  # type: ignore[attr-defined]  # leave the creation window
    other_video = await _resolve(client, adapters, "budgetvid03")
    blocked = await client.post("/api/analyses", json={"video_id": other_video}, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "budget_exhausted"
    assert (await _quota(client, headers))["used"] == 1


async def test_each_summarizer_call_is_recorded_once(
    client: AsyncClient, adapters: Adapters
) -> None:
    adapters.summarizer.chunks = list(SUMMARY_SCRIPT)  # type: ignore[attr-defined]
    headers = await _register(client)
    video_id = await _resolve(client, adapters, "budgetvid04")

    created = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert created.status_code == 201, created.text
    await _wait_terminal(client, headers, created.json()["id"])

    ledger = adapters.budget_ledger
    assert ledger.recorded == [0.01]  # type: ignore[attr-defined]
    assert ledger.spent_usd == 0.01  # type: ignore[attr-defined]
    assert len(adapters.summarizer.prompts) == 1  # type: ignore[attr-defined]


async def test_map_reduce_records_n_plus_one_calls(
    settings: Settings,
) -> None:
    tuned = settings.model_copy(
        update={"analysis_chunk_chars": 40, "analysis_max_input_chars": 10_000}
    )
    summarizer = FakeSummarizer(
        responder=lambda prompt: (
            "要点" if "字幕片段：" in prompt else "## 摘要\n内容\n## 思维导图\n- 主题"
        )
    )
    ledger = FakeBudgetLedger(budget_usd=10.0)
    adapters = make_fake_adapters(summarizer=summarizer, budget_ledger=ledger)

    app, transport = _client_for(tuned, adapters)
    async with LifespanManager(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = await _register(client)
            key = "budgetchun1"
            url = _url(key)
            adapters.video_source.videos[url] = sample_video(platform_video_id=key)  # type: ignore[attr-defined]
            adapters.video_source.subtitles[(key, "zh-Hans")] = SubtitlePayload(  # type: ignore[attr-defined]
                track=sample_subtitle_track(),
                cues=[
                    (0.0, 2.0, "第一段内容比较长需要独立成块"),
                    (2.0, 4.0, "第二段内容也比较长需要独立成块"),
                    (4.0, 6.0, "第三段内容同样比较长需要独立成块"),
                ],
                text="",
            )
            resolved = await client.post("/api/videos/resolve", json={"url": url})
            assert resolved.status_code == 200, resolved.text
            video_id = resolved.json()["video"]["id"]

            created = await client.post(
                "/api/analyses", json={"video_id": video_id}, headers=headers
            )
            assert created.status_code == 201, created.text
            detail = await _wait_terminal(client, headers, created.json()["id"])
            assert detail["status"] == "completed", detail

    prompts = len(summarizer.prompts)
    assert prompts >= 3  # at least two map calls plus the merge
    assert len(ledger.recorded) == prompts
    assert set(ledger.recorded) == {0.01}
    assert ledger.spent_usd == prompts * 0.01


async def test_db_budget_ledger_accumulates_per_shanghai_day(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'budget.db').as_posix()}",
        data_dir=tmp_path / "data",
        daily_budget_usd=1.0,
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings)
    clock = FrozenClock()
    try:
        await init_db(engine)
        ledger = DbBudgetLedger(sessionmaker, clock, settings)

        assert await ledger.can_spend(0.6) is True
        await ledger.record(0.6)
        assert await ledger.can_spend(0.4) is True
        assert await ledger.can_spend(0.5) is False

        await ledger.record(0.4)
        assert await ledger.spent_today() == 1.0
        assert await ledger.can_spend(0.01) is False

        # A new Asia/Shanghai day starts from zero.
        clock.advance(days=1)
        assert clock.today() == date(2026, 1, 16)
        assert await ledger.spent_today() == 0.0
        assert await ledger.can_spend(0.5) is True
    finally:
        await engine.dispose()
