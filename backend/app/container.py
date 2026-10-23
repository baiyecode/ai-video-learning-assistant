"""Composition root: the set of ports every business module receives."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .ports import BudgetLedger, Clock, MediaStore, Summarizer, VideoSource


@dataclass(frozen=True, slots=True)
class Adapters:
    video_source: VideoSource
    media_store: MediaStore
    summarizer: Summarizer
    clock: Clock
    budget_ledger: BudgetLedger


def build_production_adapters(settings: Settings) -> Adapters:
    """Wire real adapters. Import-safe: concrete SDKs are imported lazily by the adapters.

    The concrete implementations are filled in by their owning tickets; until then they
    raise ``NotImplementedError`` when used, never on import or construction.
    """
    from .adapters.db_budget import DbBudgetLedger
    from .adapters.deepseek_summarizer import DeepSeekSummarizer
    from .adapters.fs_media_store import FsMediaStore
    from .adapters.system_clock import SystemClock
    from .adapters.ytdlp_source import YtDlpVideoSource

    return Adapters(
        video_source=YtDlpVideoSource(settings),
        media_store=FsMediaStore(settings),
        summarizer=DeepSeekSummarizer(settings),
        clock=SystemClock(),
        budget_ledger=DbBudgetLedger(),
    )
