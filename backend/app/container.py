"""Composition root: the set of ports every business module receives."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .ports import BillingGateway, BudgetLedger, Clock, MediaStore, Summarizer, VideoSource


@dataclass(frozen=True, slots=True)
class Adapters:
    video_source: VideoSource
    media_store: MediaStore
    summarizer: Summarizer
    clock: Clock
    budget_ledger: BudgetLedger
    billing_gateway: BillingGateway


def build_production_adapters(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> Adapters:
    """Wire real adapters. Import-safe: concrete SDKs are imported lazily by the adapters.

    ``sessionmaker`` binds the SQLite budget ledger to the application database; it is
    optional only so type-checking tests can build the container without an engine.
    """
    from .adapters.db_budget import DbBudgetLedger
    from .adapters.system_clock import SystemClock

    clock = SystemClock()
    if settings.fake_adapters:
        from .adapters.demo import DemoBillingGateway, DemoMediaStore, DemoSummarizer, DemoVideoSource

        return Adapters(
            video_source=DemoVideoSource(),
            media_store=DemoMediaStore(),
            summarizer=DemoSummarizer(),
            clock=clock,
            budget_ledger=DbBudgetLedger(sessionmaker, clock, settings),
            billing_gateway=DemoBillingGateway(),
        )

    from .adapters.deepseek_summarizer import DeepSeekSummarizer
    from .adapters.fs_media_store import FsMediaStore
    from .adapters.stripe_billing import StripeBillingGateway
    from .adapters.ytdlp_source import YtDlpVideoSource

    return Adapters(
        video_source=YtDlpVideoSource(settings),
        media_store=FsMediaStore(settings),
        summarizer=DeepSeekSummarizer(settings),
        clock=clock,
        budget_ledger=DbBudgetLedger(sessionmaker, clock, settings),
        billing_gateway=StripeBillingGateway(settings),
    )
