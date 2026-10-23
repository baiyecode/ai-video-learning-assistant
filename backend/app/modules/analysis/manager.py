"""Background Analysis generation and Quota settlement.

Generation is an asyncio task owned by ``app.state`` (never by an HTTP connection),
so a dropped SSE connection cannot cancel it. On completion the Quota reservation is
moved to ``consumed``; on any failure it is released so the user can retry.

The manager is started by the application lifespan. Startup recovery fails rows left
``pending``/``streaming`` by a previous process and releases their reserved Quota
exactly once, which also clears the partial unique index so a retry can run.

SSE readers wait on the manager's condition instead of polling the database.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.container import Adapters
from app.errors import AppError, ErrorCode
from app.modules.catalog.models import Video
from app.ports import Clock

from . import generation, quota
from .models import ACTIVE_STATUSES, Analysis, AnalysisStatus

logger = logging.getLogger("app.modules.analysis")

# Persist a streamed summary at most this often (characters or seconds); every
# delta is still streamed and the final text is always persisted.
_PERSIST_CHARS = 200
_PERSIST_INTERVAL_SECONDS = 0.5


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
        self._started = False
        # Event-driven wake-up for SSE readers. One condition is enough: readers only
        # need to know that *some* Analysis changed, then re-read their own row.
        self._condition = asyncio.Condition()
        self._version = 0

    async def start(self) -> None:
        """Idempotent startup: fail rows interrupted by a previous process."""
        if self._started:
            return
        await self._recover_interrupted()
        self._started = True

    async def _recover_interrupted(self) -> None:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(Analysis).where(Analysis.status.in_(ACTIVE_STATUSES))
                )
            ).all()
            for analysis in rows:
                analysis.status = AnalysisStatus.FAILED.value
                analysis.error_code = ErrorCode.ANALYSIS_FAILED.value
                analysis.completed_at = now
                analysis.updated_at = now
                # Release once per interrupted row; a retry then has a free Quota
                # unit and the partial unique index no longer blocks it.
                await quota.release(
                    session,
                    analysis.account_id,
                    quota.quota_day(analysis.created_at),
                )
            if rows:
                await session.commit()
        if rows:
            logger.warning(
                "analyses_recovered_after_restart",
                extra={
                    "event": "analyses_recovered_after_restart",
                    "count": len(rows),
                },
            )

    def submit(self, analysis_id: str) -> None:
        """Start generation for a freshly created Analysis."""
        task = asyncio.create_task(self._run(analysis_id), name=f"analysis-{analysis_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Resolve once every submitted generation reached a terminal state."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        """Cancel in-flight generation; the next startup recovers their rows."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def version(self) -> int:
        """Monotonic change counter; capture before reading the row."""
        return self._version

    async def wait_for_change(self, version: int, *, keepalive_seconds: float = 15.0) -> int:
        """Block until a change after ``version`` (or the keep-alive interval)."""
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._version != version),
                    timeout=keepalive_seconds,
                )
            except TimeoutError:
                pass
            return self._version

    async def _notify(self) -> None:
        async with self._condition:
            self._version += 1
            self._condition.notify_all()

    async def _run(self, analysis_id: str) -> None:
        try:
            plan = await self._prepare(analysis_id)
            if plan is None:
                return
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
            if video is None:
                await self._fail_in_session(session, analysis)
                return None

            try:
                # Read ONLY the immutable snapshot taken at creation. The mutable
                # Subtitle row may have been replaced since; it must not affect this
                # Analysis's inputs.
                plan = generation.build_plan(
                    title=video.title,
                    duration_seconds=video.duration_seconds,
                    subtitle_source=analysis.subtitle_source,
                    cues=generation.cues_from_stored(
                        analysis.subtitle_cues, fallback_text=analysis.subtitle_text
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
        loop = asyncio.get_running_loop()
        persisted = ""
        persisted_at = loop.time()
        try:
            # One deadline for the whole map-reduce run: partial summaries must leave
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
                await self._ensure_call_budget()
                try:
                    async for chunk in self._adapters.summarizer.stream(prompt=prompt):
                        if not splitter.feed(chunk):
                            continue
                        summary = splitter.summary
                        # Throttle writes: coalesce small deltas so SQLite is not
                        # rewritten for every few characters. The text is never
                        # dropped; ``_complete`` always persists the final result.
                        if (
                            len(summary) - len(persisted) >= _PERSIST_CHARS
                            or loop.time() - persisted_at >= _PERSIST_INTERVAL_SECONDS
                        ):
                            await self._persist_summary(analysis_id, summary)
                            persisted = summary
                            persisted_at = loop.time()
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
            code = ErrorCode.ANALYSIS_FAILED
            if isinstance(failure, AppError) and failure.code == ErrorCode.BUDGET_EXHAUSTED.value:
                # A mid-generation budget stop is its own stable code, not a generic
                # analysis failure; the Quota reservation is still released.
                code = ErrorCode.BUDGET_EXHAUSTED
            await self._fail(analysis_id, code=code)
            return

        summary, mindmap = splitter.finish()
        await self._complete(analysis_id, summary, mindmap)

    async def _ensure_call_budget(self) -> None:
        """Gate one more billed call; may raise ``budget_exhausted``."""
        await generation.ensure_budget(
            self._adapters.budget_ledger,
            estimated_usd=self._settings.analysis_cost_per_call_usd,
            clock=self._clock,
            daily_budget_usd=self._settings.daily_budget_usd,
        )

    async def _partial_summary(self, prompt: str) -> str:
        """Consume one map call whole; an empty result means the model failed."""
        await self._ensure_call_budget()
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
        persisted = False
        async with self._sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None or analysis.status != AnalysisStatus.STREAMING.value:
                return
            analysis.summary_markdown = summary
            analysis.updated_at = self._clock.now()
            await session.commit()
            persisted = True
        if persisted:
            await self._notify()

    async def _complete(self, analysis_id: str, summary: str, mindmap: str) -> None:
        completed = False
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
            completed = True
        if completed:
            await self._notify()

    async def _fail(self, analysis_id: str, *, code: ErrorCode = ErrorCode.ANALYSIS_FAILED) -> None:
        async with self._sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None or not _settleable(analysis):
                return
            await self._fail_in_session(session, analysis, code=code)

    async def _fail_in_session(
        self,
        session: AsyncSession,
        analysis: Analysis,
        *,
        code: ErrorCode = ErrorCode.ANALYSIS_FAILED,
    ) -> None:
        now = self._clock.now()
        analysis.status = AnalysisStatus.FAILED.value
        analysis.error_code = code.value
        analysis.completed_at = now
        analysis.updated_at = now
        await quota.release(session, analysis.account_id, quota.quota_day(analysis.created_at))
        await session.commit()
        await self._notify()


def _settleable(analysis: Analysis) -> bool:
    return analysis.status in (AnalysisStatus.PENDING.value, AnalysisStatus.STREAMING.value)
