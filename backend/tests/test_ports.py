from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.config import Settings
from app.container import build_production_adapters
from app.ports import BudgetLedger, Clock, MediaStore, Summarizer, VideoSource

from tests.fakes import FakeBudgetLedger, FakeMediaStore, FakeSummarizer, FrozenClock, sample_video


def test_production_adapters_expose_every_port(settings: Settings) -> None:
    adapters = build_production_adapters(settings)

    assert isinstance(adapters.video_source, VideoSource)
    assert isinstance(adapters.media_store, MediaStore)
    assert isinstance(adapters.summarizer, Summarizer)
    assert isinstance(adapters.clock, Clock)
    assert isinstance(adapters.budget_ledger, BudgetLedger)


def test_frozen_clock_reports_shanghai_calendar_day() -> None:
    clock = FrozenClock(instant=datetime(2026, 1, 1, 17, 0, tzinfo=UTC))

    assert clock.now() == datetime(2026, 1, 1, 17, 0, tzinfo=UTC)
    # 17:00 UTC is 01:00 on the next calendar day in Asia/Shanghai.
    assert clock.today().isoformat() == "2026-01-02"


async def test_fake_media_store_writes_file_and_reports_progress(tmp_path) -> None:
    store = FakeMediaStore(content=b"abc")
    phases: list[tuple[str, float]] = []

    path = await store.download(
        video=sample_video(),
        format_id="best",
        dest_dir=tmp_path,
        on_progress=lambda phase, progress: phases.append((phase, progress)),
    )

    assert path.read_bytes() == b"abc"
    assert phases[0] == ("downloading", 0.0)
    assert phases[-1] == ("merging", 1.0)
    assert store.downloads[0]["format_id"] == "best"


async def test_fake_summarizer_streams_scripted_chunks() -> None:
    summarizer = FakeSummarizer(chunks=["甲", "乙"])

    received = [chunk async for chunk in summarizer.stream(prompt="总结")]

    assert received == ["甲", "乙"]
    assert summarizer.prompts == ["总结"]


async def test_fake_budget_ledger_blocks_spending_over_budget() -> None:
    ledger = FakeBudgetLedger(budget_usd=1.0, spent_usd=0.9)

    assert await ledger.can_spend(0.05) is True
    assert await ledger.can_spend(0.2) is False

    await ledger.record(0.05)
    assert ledger.spent_usd == pytest.approx(0.95)
