"""Background Analysis generation and Quota settlement.

Generation is an asyncio task owned by ``app.state`` (never by an HTTP connection),
so a dropped SSE connection cannot cancel it. On completion the Quota reservation is
moved to ``consumed``; on any failure it is released so the user can retry.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.container import Adapters
from app.errors import ErrorCode
from app.modules.catalog.models import Subtitle, Video
from app.ports import Clock

from . import generation, quota
from .models import Analysis, AnalysisStatus

logger = logging.getLogger("app.modules.analysis")


class AnalysisManager:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        adapters: Adapters,
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._adapters = adapters
        self._settings = settings
        self._clock: Clock = adapters.clock
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, analysis_id: str) -> None:
        """Start generation for a freshly created Analysis."""
        task = asyncio.create_task(self._run(analysis_id), name=f"analysis-{analysis_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Resolve once every submitted generation reached a terminal state."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run(self, analysis_id: str) -> None:
        try:
            plan = await self._prepare(analysis_id)
            if plan is None:
                return
            await generation.ensure_budget(
                self._adapters.budget_ledger,
                estimated_usd=self._settings.analysis_cost_per_call_usd,
                clock=self._clock,
                daily_budget_usd=self._settings.daily_budget_usd,
            )
            await self._generate(analysis_id, plan)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a crash must still settle the row and Quota
            logger.exception(
                "analysis_generation_crashed",
                extra={"event": "analysis_generation_crashed", "analysis_id": analysis_id},
            )
            await self._fail(analysis_id)

    async def _prepare(self, analysis_id: str) -> generation.GenerationPlan | None:
        """Plan cue-aware chunks and move the row to ``streaming``."""
        async with self._sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None or analysis.status != AnalysisStatus.PENDING.value:
                return None
            video = await session.get(Video, analysis.video_id)
            subtitle = (
                await session.get(Subtitle, analysis.subtitle_id)
                if analysis.subtitle_id
                else None
            )
            if video is None or subtitle is None:
                await self._fail_in_session(session, analysis)
                return None

            try:
                plan = generation.build_plan(
                    title=video.title,
                    duration_seconds=video.duration_seconds,
                    subtitle_source=analysis.subtitle_source,
                    cues=generation.cues_from_stored(
                        subtitle.cues_json, fallback_text=subtitle.text
                    ),
                    chunk_chars=self._settings.analysis_chunk_chars,
                    max_input_chars=self._settings.analysis_max_input_chars,
                )
            except ValueError:
                # Subtitle content was empty: fail the Analysis instead of crashing.
                await self._fail_in_session(session, analysis)
                return None
            analysis.status = AnalysisStatus.STREAMING.value
            # Visible in the ``meta`` SSE event before the first delta: the UI can
            # warn that the result is based on truncated input from the start.
            analysis.truncated = plan.truncated
            analysis.updated_at = self._clock.now()
            await session.commit()
            logger.info(
                "analysis_generation_planned",
                extra={
                    "event": "analysis_generation_planned",
                    "analysis_id": analysis_id,
                    "chunks": len(plan.chunk_prompts) or 1,
                    "truncated": plan.truncated,
                },
            )
            return plan

    async def _generate(self, analysis_id: str, plan: generation.GenerationPlan) -> None:
        splitter = generation.OutputSplitter()
        failure: BaseException | None = None
        try:
            # One budget for the whole map-reduce run: partial summaries must leave
            # enough time for the final merge call.
            async with asyncio.timeout(self._settings.analysis_timeout_seconds):
                prompt = plan.direct_prompt
                if plan.needs_merge:
                    partials = [
                        await self._partial_summary(chunk_prompt)
                        for chunk_prompt in plan.chunk_prompts
                    ]
                    prompt = generation.build_merge_prompt(plan, partial_summaries=partials)
                if prompt is None:
                    raise RuntimeError("generation plan has no prompt")
                # Only the final (or single) call is streamed and persisted; the map
                # calls produce intermediate summaries that are never shown.
                try:
                    async for chunk in self._adapters.summarizer.stream(prompt=prompt):
                        if splitter.feed(chunk):
                            await self._persist_summary(analysis_id, splitter.summary)
                finally:
                    # Every Summarizer call is billed, including a call that failed
                    # halfway: upstream tokens were already consumed.
                    await self._record_call_cost()
        except TimeoutError as exc:
            failure = exc
        except Exception as exc:  # noqa: BLE001 - any adapter failure becomes analysis_failed
            failure = exc

        if failure is not None or not splitter.has_content:
            if failure is not None:
                logger.warning(
                    "analysis_generation_failed",
                    extra={
                        "event": "analysis_generation_failed",
                        "analysis_id": analysis_id,
                        "error_type": type(failure).__name__,
                    },
                )
            await self._fail(analysis_id)
            return

        summary, mindmap = splitter.finish()
        await self._complete(analysis_id, summary, mindmap)

    async def _partial_summary(self, prompt: str) -> str:
        """Consume one map call whole; an empty result means the model failed."""
        try:
            parts = [chunk async for chunk in self._adapters.summarizer.stream(prompt=prompt)]
            text = "".join(parts).strip()
        finally:
            await self._record_call_cost()
        if not text:
            raise RuntimeError("empty partial summary")
        return text

    async def _record_call_cost(self) -> None:
        """Bill one Summarizer call. A ledger outage must not fail the generation."""
        try:
            await self._adapters.budget_ledger.record(
                self._settings.analysis_cost_per_call_usd
            )
        except Exception:  # noqa: BLE001 - recording is best-effort after the spend
            logger.warning(
                "budget_record_failed",
                extra={"event": "budget_record_failed", "error_type": "budget"},
            )

    async def _persist_summary(self, analysis_id: str, summary: str) -> None:
        async with self._sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None or analysis.status != AnalysisStatus.STREAMING.value:
                return
            analysis.summary_markdown = summary
            analysis.updated_at = self._clock.now()
            await session.commit()

    async def _complete(self, analysis_id: str, summary: str, mindmap: str) -> None:
        async with self._sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None or not _settleable(analysis):
                return
            now = self._clock.now()
            analysis.summary_markdown = summary
            analysis.mindmap_markdown = mindmap
            analysis.status = AnalysisStatus.COMPLETED.value
            analysis.error_code = None
            analysis.completed_at = now
            analysis.updated_at = now
            await quota.consume(
                session, analysis.account_id, quota.quota_day(analysis.created_at)
            )
            await session.commit()

    async def _fail(self, analysis_id: str) -> None:
        async with self._sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None or not _settleable(analysis):
                return
            await self._fail_in_session(session, analysis)

    async def _fail_in_session(self, session: AsyncSession, analysis: Analysis) -> None:
        now = self._clock.now()
        analysis.status = AnalysisStatus.FAILED.value
        analysis.error_code = ErrorCode.ANALYSIS_FAILED.value
        analysis.completed_at = now
        analysis.updated_at = now
        await quota.release(session, analysis.account_id, quota.quota_day(analysis.created_at))
        await session.commit()


def _settleable(analysis: Analysis) -> bool:
    return analysis.status in (AnalysisStatus.PENDING.value, AnalysisStatus.STREAMING.value)
