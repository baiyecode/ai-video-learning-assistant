"""Issue #9: cue-aware chunking and map-reduce generation for long Subtitles.

The planning seam is exercised directly (pure functions); end-to-end coverage goes
through the in-process HTTP seam with a 2-hour, 1200-cue Subtitle sample.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from app.modules.analysis import generation
from app.ports import SubtitlePayload
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from tests.auth_flows import verified_account
from tests.fakes import (
    FakeSummarizer,
    make_fake_adapters,
    sample_subtitle_track,
    sample_video,
)

CUE_TEXT = "这是一句用于分块测试的字幕内容"
PASSWORD = "correct-horse"
TERMINAL = {"completed", "failed"}


def long_subtitle_cues(
    count: int, *, duration_seconds: int = 7200, markers: dict[int, str] | None = None
) -> list[generation.Cue]:
    """A dense 2-hour Subtitle; every cue has the same 18-character length."""
    markers = markers or {}
    step = duration_seconds / count
    cues: list[generation.Cue] = []
    for index in range(count):
        marker = markers.get(index)
        if marker:
            text = marker + "。" * (18 - len(marker))
        else:
            text = f"第{index:04d}句字幕内容用于覆盖测试内容"
        assert len(text) == 18
        cues.append(generation.Cue(start=index * step, end=(index + 1) * step, text=text))
    return cues


def make_cues(count: int, *, cue_seconds: float = 6.0) -> list[generation.Cue]:
    """A 2-hour Chinese Subtitle: ``count`` cues of ``cue_seconds`` each."""
    return [
        generation.Cue(
            start=index * cue_seconds,
            end=(index + 1) * cue_seconds,
            text=f"{CUE_TEXT}{index:04d}",
        )
        for index in range(count)
    ]


def test_chunks_split_only_between_cues_and_respect_the_char_budget() -> None:
    cues = make_cues(120)

    chunks = generation.plan_chunks(cues, max_chars=120)

    assert len(chunks) > 1
    # Splitting at cue boundaries: joining chunk texts rebuilds the whole Subtitle.
    assert "\n".join(chunk.text for chunk in chunks) == "\n".join(cue.text for cue in cues)
    assert all(chunk.char_count <= 120 for chunk in chunks)
    # Cues are packed, not one chunk per cue.
    assert max(len(chunk.cues) for chunk in chunks) > 1
    # Every chunk knows its place in the full timeline.
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.count for chunk in chunks} == {len(chunks)}


def test_oversized_cue_is_kept_whole_even_over_the_budget() -> None:
    huge = generation.Cue(start=0.0, end=10.0, text="长" * 500)
    short = generation.Cue(start=10.0, end=20.0, text="短句")

    chunks = generation.plan_chunks([huge, short], max_chars=100)

    assert [cue.text for cue in chunks[0].cues] == ["长" * 500]
    assert chunks[0].char_count == 500
    assert [cue.text for cue in chunks[1].cues] == ["短句"]


def make_chunk(index: int, *, count: int, label: str, chars: int = 100) -> generation.Chunk:
    text = f"{label}-{index:02d}" + "字" * (chars - len(label) - 3)
    return generation.Chunk(
        cues=(generation.Cue(start=index * 60.0, end=(index + 1) * 60.0, text=text),),
        index=index,
        count=count,
    )


def test_input_over_the_limit_keeps_chunks_distributed_across_the_timeline() -> None:
    labels = ["开头", *(["中段"] * 10), "结尾"]
    chunks = [make_chunk(i, count=12, label=label) for i, label in enumerate(labels)]

    selected, truncated = generation.select_chunks(chunks, max_input_chars=350)

    assert truncated is True
    # First, middle and last chunk stay; the gap between them is skipped.
    assert [chunk.index for chunk in selected] == [0, 6, 11]
    assert sum(chunk.char_count for chunk in selected) <= 350
    joined = "\n".join(chunk.text for chunk in selected)
    assert labels[0] in joined and labels[6] in joined and labels[11] in joined


def test_input_within_the_limit_keeps_every_chunk() -> None:
    chunks = [make_chunk(i, count=4, label="内容") for i in range(4)]

    selected, truncated = generation.select_chunks(chunks, max_input_chars=10_000)

    assert selected == chunks
    assert truncated is False


def test_short_subtitle_keeps_a_single_direct_prompt() -> None:
    cues = make_cues(3)

    plan = generation.build_plan(
        title="示例视频",
        duration_seconds=18,
        subtitle_source="manual",
        cues=cues,
        chunk_chars=6000,
        max_input_chars=120_000,
    )

    assert plan.truncated is False
    assert plan.needs_merge is False
    assert plan.chunk_prompts == ()
    assert plan.direct_prompt is not None
    assert "示例视频" in plan.direct_prompt
    assert "人工" in plan.direct_prompt
    for cue in cues:
        assert cue.text in plan.direct_prompt
    assert "## 思维导图" in plan.direct_prompt
    assert "分段摘要" not in plan.direct_prompt


def test_long_subtitle_builds_one_prompt_per_chunk_and_a_merge_prompt() -> None:
    cues = make_cues(120)

    plan = generation.build_plan(
        title="两小时课程",
        duration_seconds=7200,
        subtitle_source="auto",
        cues=cues,
        chunk_chars=200,
        max_input_chars=120_000,
    )

    assert plan.truncated is False
    assert plan.needs_merge is True
    assert plan.direct_prompt is None
    assert len(plan.chunk_prompts) > 1
    assert len(plan.segment_labels) == len(plan.chunk_prompts)
    # Every cue reaches exactly one map prompt, in timeline order.
    prompts_text = "\n".join(plan.chunk_prompts)
    for cue in cues:
        assert prompts_text.count(cue.text) == 1
    assert prompts_text.index(cues[0].text) < prompts_text.index(cues[-1].text)
    assert "## 思维导图" not in prompts_text

    partials = [f"分段摘要{i}" for i in range(len(plan.chunk_prompts))]
    merge_prompt = generation.build_merge_prompt(plan, partial_summaries=partials)

    assert "两小时课程" in merge_prompt
    assert "## 思维导图" in merge_prompt
    for partial in partials:
        assert partial in merge_prompt
    assert merge_prompt.index(partials[0]) < merge_prompt.index(partials[-1])


# ----------------------------------------------------------------------- HTTP seam

MARKERS = ("开头标记内容", "中段标记内容", "结尾标记内容")


def echo_markers_responder(prompt: str) -> str:
    """Echo the coverage markers found in the prompt (map and merge calls alike)."""
    found = [marker for marker in MARKERS if marker in prompt]
    body = "\n".join(f"- 覆盖 {marker}" for marker in found)
    return f"## 归并摘要\n{body}\n## 思维导图\n- 视频结构\n  - 章节\n"


async def _register(
    adapters: Adapters, client: AsyncClient, email: str = "learner@example.com"
) -> dict[str, str]:
    return await verified_account(client, adapters, email=email, password=PASSWORD)


async def _resolve_long_video(
    client: AsyncClient,
    adapters: Adapters,
    *,
    platform_video_id: str,
    cues: list[generation.Cue],
    duration_seconds: int = 7200,
) -> str:
    url = f"https://www.youtube.com/watch?v={platform_video_id}"
    adapters.video_source.videos[url] = sample_video(  # type: ignore[attr-defined]
        platform_video_id=platform_video_id, duration_seconds=duration_seconds
    )
    track = sample_subtitle_track()
    adapters.video_source.subtitles[(platform_video_id, track.language)] = (  # type: ignore[attr-defined]
        SubtitlePayload(
            track=track,
            cues=[(cue.start, cue.end, cue.text) for cue in cues],
            text="\n".join(cue.text for cue in cues),
        )
    )
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


async def _create(client: AsyncClient, headers: dict[str, str], video_id: str) -> str:
    response = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _wait_terminal(
    client: AsyncClient, headers: dict[str, str], analysis_id: str, *, limit_seconds: float = 10.0
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_seconds
    while loop.time() < deadline:
        response = await client.get(f"/api/analyses/{analysis_id}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
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
) -> list[tuple[str, dict[str, Any]]]:
    response = await client.get(f"/api/analyses/{analysis_id}/stream", headers=headers)
    assert response.status_code == 200, response.text
    return _parse_events(response.text)


async def _me(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/api/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["quota"]


async def test_two_hour_subtitle_covers_beginning_middle_and_end(
    client: AsyncClient, adapters: Adapters
) -> None:
    summarizer = adapters.summarizer
    summarizer.responder = echo_markers_responder  # type: ignore[attr-defined]
    headers = await _register(adapters, client)
    cues = long_subtitle_cues(
        1200,
        markers={0: "开头标记内容", 600: "中段标记内容", 1199: "结尾标记内容"},
    )
    video_id = await _resolve_long_video(
        client, adapters, platform_video_id="longvid0001", cues=cues
    )

    analysis_id = await _create(client, headers, video_id)
    detail = await _wait_terminal(client, headers, analysis_id)

    assert detail["status"] == "completed"
    assert detail["truncated"] is False
    summary = detail["summary_markdown"]
    for marker in MARKERS:
        assert marker in summary
    assert detail["mindmap_markdown"]

    prompts = summarizer.prompts  # type: ignore[attr-defined]
    assert len(prompts) > 1
    map_prompts, merge_prompt = prompts[:-1], prompts[-1]
    assert all("分段摘要" not in prompt for prompt in map_prompts)
    assert "分段摘要" in merge_prompt
    # Beginning, middle and end all reached the merge call.
    for marker in MARKERS:
        assert marker in merge_prompt

    events = await _stream(client, headers, analysis_id)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-2:] == ["mindmap", "done"]
    assert set(names[1:-2]) == {"delta"}
    streamed = "".join(payload["text"] for name, payload in events if name == "delta")
    assert streamed == summary


async def test_short_subtitle_still_uses_a_single_generation_call(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = await _register(adapters, client)
    cues = long_subtitle_cues(3, duration_seconds=18)
    video_id = await _resolve_long_video(
        client, adapters, platform_video_id="shortvid001", cues=cues, duration_seconds=18
    )

    analysis_id = await _create(client, headers, video_id)
    detail = await _wait_terminal(client, headers, analysis_id)

    assert detail["status"] == "completed"
    assert detail["truncated"] is False
    assert len(adapters.summarizer.prompts) == 1  # type: ignore[attr-defined]


async def test_input_over_the_budget_keeps_the_tail_and_flags_truncation(
    settings: Settings,
) -> None:
    custom = settings.model_copy(
        update={"analysis_chunk_chars": 400, "analysis_max_input_chars": 1200}
    )
    summarizer = FakeSummarizer(responder=echo_markers_responder)
    custom_adapters = make_fake_adapters(summarizer=summarizer)
    app = create_app(settings=custom, adapters=custom_adapters)

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = await _register(custom_adapters, client, "truncated@example.com")
            cues = long_subtitle_cues(
                100,
                markers={
                    0: "开头标记内容",
                    30: "丢弃标记内容",
                    50: "中段标记内容",
                    99: "结尾标记内容",
                },
            )
            video_id = await _resolve_long_video(
                client, custom_adapters, platform_video_id="truncvid001", cues=cues
            )

            analysis_id = await _create(client, headers, video_id)
            detail = await _wait_terminal(client, headers, analysis_id)

            assert detail["status"] == "completed"
            assert detail["truncated"] is True
            # The tail is kept: the result still reflects the end of the video.
            for marker in MARKERS:
                assert marker in detail["summary_markdown"]
            # The skipped middle chunk never reaches the model, and the UI is told.
            assert all("丢弃标记内容" not in prompt for prompt in summarizer.prompts)
            assert len(summarizer.prompts) > 1

            events = await _stream(client, headers, analysis_id)
            assert events[0][0] == "meta"
            assert events[0][1]["truncated"] is True
            assert events[-2][0] == "mindmap"


async def test_long_generation_respects_the_end_to_end_timeout(settings: Settings) -> None:
    custom = settings.model_copy(update={"analysis_timeout_seconds": 0.05})
    summarizer = FakeSummarizer(responder=echo_markers_responder, hang_seconds=5.0)
    custom_adapters = make_fake_adapters(summarizer=summarizer)
    app = create_app(settings=custom, adapters=custom_adapters)

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = await _register(custom_adapters, client, "longtimeout@example.com")
            cues = long_subtitle_cues(1200, markers={0: "开头标记内容"})
            video_id = await _resolve_long_video(
                client, custom_adapters, platform_video_id="timeoutvid2", cues=cues
            )

            analysis_id = await _create(client, headers, video_id)
            detail = await _wait_terminal(client, headers, analysis_id)

            assert detail["status"] == "failed"
            assert detail["error"]["code"] == "analysis_failed"
            assert (await _me(client, headers))["used"] == 0
