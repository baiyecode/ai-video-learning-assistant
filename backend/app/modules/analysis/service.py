"""Analysis use-cases: create (with Quota reservation) and ownership-checked reads.

Validation order matters: Video existence, DRM/members and Subtitle availability are
checked *before* a Quota unit is reserved, so rejected requests never consume Quota.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app import messages
from app.config import Settings
from app.errors import AppError, ErrorCode
from app.modules.billing.service import membership_state
from app.modules.catalog.models import Subtitle, Video
from app.ports import BudgetLedger, Clock
from app.ratelimit import RateLimiter
from app.timeutil import as_utc

from . import generation, quota
from .generation import MESSAGE_ANALYSIS_FAILED
from .models import ACTIVE_STATUSES, Analysis, AnalysisStatus
from .schemas import AnalysisErrorOut, AnalysisOut, AnalysisVideoOut, QuotaOut

logger = logging.getLogger("app.modules.analysis")

MESSAGE_ANALYSIS_NOT_FOUND = "分析不存在或已失效"
MESSAGE_QUOTA_EXHAUSTED = "今日 Analysis Quota 已用完，请于 {reset}（北京时间）后再试"
MESSAGE_BUSY = "服务繁忙，请稍后重试"

_MESSAGE_BY_ERROR_CODE = {
    ErrorCode.ANALYSIS_FAILED.value: MESSAGE_ANALYSIS_FAILED,
    ErrorCode.BUDGET_EXHAUSTED.value: "今日 AI 预算已用完，请稍后再试",
}

_MAX_WRITE_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class CreateResult:
    analysis: Analysis
    video: Video | None
    created: bool
    membership: str


def _iso(value: datetime | None) -> str | None:
    aware = as_utc(value)
    return aware.isoformat() if aware is not None else None


def _quota_exhausted(clock: Clock, settings: Settings) -> AppError:
    limit = settings.analysis_daily_quota
    resets_at = quota.next_reset_at(clock)
    return AppError(
        429,
        ErrorCode.QUOTA_EXHAUSTED,
        MESSAGE_QUOTA_EXHAUSTED.format(reset=resets_at.strftime("%Y-%m-%d %H:%M")),
        {
            "daily_limit": limit,
            "used": limit,
            "remaining": 0,
            "resets_at": resets_at.isoformat(),
        },
    )


async def _find_active(
    session: AsyncSession, account_id: str, video_id: str
) -> Analysis | None:
    return await session.scalar(
        select(Analysis)
        .where(
            Analysis.account_id == account_id,
            Analysis.video_id == video_id,
            Analysis.status.in_(ACTIVE_STATUSES),
        )
        .order_by(Analysis.created_at.desc())
    )


async def membership_status(session: AsyncSession, account_id: str, *, now) -> str:
    """Delegate to billing's single membership read (derivation lives over there)."""
    state = await membership_state(session, account_id, now=now)
    return state.status


async def _create_once(
    session: AsyncSession,
    clock: Clock,
    settings: Settings,
    *,
    account_id: str,
    video_id: str,
    force: bool,
    rate_limiter: RateLimiter,
    budget_ledger: BudgetLedger,
) -> CreateResult:
    video = await session.get(Video, video_id)
    if video is None:
        raise AppError(404, ErrorCode.VIDEO_NOT_FOUND, messages.VIDEO_NOT_FOUND)
    if video.is_drm:
        raise AppError(403, ErrorCode.DRM_PROTECTED, messages.DRM_PROTECTED)
    if video.is_members_only:
        raise AppError(403, ErrorCode.MEMBERS_ONLY, messages.MEMBERS_ONLY)

    subtitle = await session.scalar(select(Subtitle).where(Subtitle.video_id == video_id))
    if subtitle is None:
        raise AppError(
            409,
            ErrorCode.SUBTITLES_UNAVAILABLE,
            messages.SUBTITLES_UNAVAILABLE,
            {"video_id": video_id},
        )

    # Read once per request through billing's single membership port: it decides
    # the Quota gate below and surfaces as the ``membership`` field on every create
    # response (new or reused). Expired VIP already presents as canceled/non-VIP.
    state = await membership_state(session, account_id, now=clock.now())

    active = await _find_active(session, account_id, video_id)
    if active is not None:
        return CreateResult(active, video, False, state.status)

    if not force:
        completed = await session.scalar(
            select(Analysis)
            .where(
                Analysis.account_id == account_id,
                Analysis.video_id == video_id,
                Analysis.status == AnalysisStatus.COMPLETED.value,
            )
            .order_by(Analysis.created_at.desc())
        )
        if completed is not None:
            return CreateResult(completed, video, False, state.status)

    # Gates for a genuinely new Analysis only: reusing an in-progress or completed
    # result above costs neither rate-limit budget nor Quota. Spec gate order
    # (ticket #22): 已登录 → 邮箱已验证 (router) → Quota/VIP → 限流. The budget cap
    # rides with Quota (a rejection there reserves nothing), and the throttle runs
    # after the reservation: a throttle refusal aborts the transaction, so the
    # reserved unit is rolled back and stays unconsumed either way.
    # Gate on every call this Analysis will make (chunks + final merge), not on
    # one call: a map-reduce run that starts without its full budget would run
    # out halfway and waste the calls already paid for.
    try:
        plan = generation.build_plan(
            title=video.title,
            duration_seconds=video.duration_seconds,
            subtitle_source=subtitle.source_type,
            cues=generation.cues_from_stored(
                subtitle.cues_json, fallback_text=subtitle.text
            ),
            chunk_chars=settings.analysis_chunk_chars,
            max_input_chars=settings.analysis_max_input_chars,
        )
        planned_calls = generation.planned_call_count(plan)
    except ValueError:
        # Empty Subtitle content is settled by generation as analysis_failed;
        # the cheapest possible plan is still one call.
        planned_calls = 1
    await generation.ensure_budget(
        budget_ledger,
        estimated_usd=settings.analysis_cost_per_call_usd * planned_calls,
        clock=clock,
        daily_budget_usd=settings.daily_budget_usd,
    )

    # VIP Membership lifts the cap without bypassing the atomic reservation: the
    # sentinel limit keeps counting units, so failure rollback still applies.
    effective_limit = (
        quota.UNLIMITED_DAILY_LIMIT
        if state.is_vip
        else settings.analysis_daily_quota
    )
    if not await quota.reserve(session, account_id, clock.today(), effective_limit):
        raise _quota_exhausted(clock, settings)

    if force or rate_limiter.last_tag("analyses.create", account_id) != video_id:
        # A repeated *non-force* request for the Video that just started is an
        # idempotent retry (double click / two tabs), not a new-analysis attempt.
        # A refusal here rolls back the transaction, un-reserving the unit above.
        rate_limiter.ensure("analyses.create", account_id)

    now = clock.now()
    analysis = Analysis(
        account_id=account_id,
        video_id=video_id,
        # Traceability only; generation reads the snapshot below.
        subtitle_id=subtitle.id,
        status=AnalysisStatus.PENDING.value,
        summary_markdown="",
        mindmap_markdown="",
        subtitle_source=subtitle.source_type,
        subtitle_language=subtitle.language,
        subtitle_text=subtitle.text,
        subtitle_cues=list(subtitle.cues_json or []),
        truncated=False,
        created_at=now,
        updated_at=now,
    )
    session.add(analysis)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent request inserted the in-progress Analysis first: its row wins
        # and this transaction's Quota reservation is rolled back with it.
        await session.rollback()
        active = await _find_active(session, account_id, video_id)
        if active is None:
            raise
        video = await session.get(Video, video_id)
        return CreateResult(active, video, False, state.status)

    # Only a committed new row consumes the per-Account creation slot; the winner of
    # a concurrent race records here and the loser above never does.
    rate_limiter.record("analyses.create", account_id, tag=video_id)
    return CreateResult(analysis, video, True, state.status)


async def create_analysis(
    session: AsyncSession,
    clock: Clock,
    settings: Settings,
    *,
    account_id: str,
    video_id: str,
    rate_limiter: RateLimiter,
    budget_ledger: BudgetLedger,
    force: bool = False,
) -> CreateResult:
    """Create or reuse an Analysis. Only a genuinely new row starts generation."""
    for attempt in range(_MAX_WRITE_ATTEMPTS):
        try:
            return await _create_once(
                session,
                clock,
                settings,
                account_id=account_id,
                video_id=video_id,
                force=force,
                rate_limiter=rate_limiter,
                budget_ledger=budget_ledger,
            )
        except OperationalError as exc:
            await session.rollback()
            message = str(exc).lower()
            writable = "locked" in message or "busy" in message
            if not writable or attempt == _MAX_WRITE_ATTEMPTS - 1:
                logger.warning(
                    "analysis_create_busy",
                    extra={"event": "analysis_create_busy", "error_type": type(exc).__name__},
                )
                raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, MESSAGE_BUSY) from exc
            # WAL writers are serialised; retry reads the winner's row and reuses it.
            await asyncio.sleep(0.02 * (attempt + 1))
    raise AssertionError("unreachable")  # pragma: no cover


async def daily_quota(
    session: AsyncSession, account_id: str, clock: Clock, settings: Settings
) -> QuotaOut:
    """This Account's Quota for the current day.

    The Quota counters belong to this module: callers that only need to *show* them
    (``/api/me``) read them here instead of digging through :mod:`.quota`. VIP
    Membership surfaces as the unlimited sentinel plus the raw subscription status.
    """
    state = await membership_state(session, account_id, now=clock.now())
    limit = (
        quota.UNLIMITED_DAILY_LIMIT
        if state.is_vip
        else settings.analysis_daily_quota
    )
    snapshot = await quota.usage(session, account_id, clock, limit)
    return QuotaOut(
        daily_limit=snapshot.daily_limit,
        used=snapshot.used,
        remaining=snapshot.remaining,
        resets_at=snapshot.resets_at.isoformat(),
        membership=state.status,
    )


async def get_analysis(
    session: AsyncSession, account_id: str, analysis_id: str
) -> tuple[Analysis, Video | None]:
    """Ownership-checked read. Other Accounts' Analyses look exactly like missing ones."""
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or analysis.account_id != account_id:
        raise AppError(404, ErrorCode.ANALYSIS_NOT_FOUND, MESSAGE_ANALYSIS_NOT_FOUND)
    video = await session.get(Video, analysis.video_id)
    return analysis, video


def error_message(code: str | None) -> str:
    if code is None:
        return MESSAGE_ANALYSIS_FAILED
    return _MESSAGE_BY_ERROR_CODE.get(code, MESSAGE_ANALYSIS_FAILED)


def to_out(analysis: Analysis, video: Video | None, membership: str) -> AnalysisOut:
    error = None
    if analysis.status == AnalysisStatus.FAILED.value:
        code = analysis.error_code or ErrorCode.ANALYSIS_FAILED.value
        error = AnalysisErrorOut(code=code, message=error_message(code))

    video_out = (
        AnalysisVideoOut(
            id=video.id,
            title=video.title,
            platform=video.platform,
            duration_seconds=video.duration_seconds,
            thumbnail_url=video.thumbnail_url,
        )
        if video is not None
        else None
    )
    return AnalysisOut(
        id=analysis.id,
        video_id=analysis.video_id,
        status=analysis.status,  # type: ignore[arg-type]
        summary_markdown=analysis.summary_markdown or "",
        mindmap_markdown=analysis.mindmap_markdown or "",
        subtitle_source=analysis.subtitle_source,  # type: ignore[arg-type]
        truncated=bool(analysis.truncated),
        error=error,
        created_at=_iso(analysis.created_at) or "",
        updated_at=_iso(analysis.updated_at) or "",
        completed_at=_iso(analysis.completed_at),
        video=video_out,
        membership=membership,
    )
