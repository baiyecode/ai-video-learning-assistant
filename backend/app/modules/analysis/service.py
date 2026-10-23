"""Analysis use-cases: create (with Quota reservation) and ownership-checked reads.

Validation order matters: Video existence, DRM/members and Subtitle availability are
checked *before* a Quota unit is reserved, so rejected requests never consume Quota.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.modules.catalog.models import Subtitle, Video
from app.ports import BudgetLedger, Clock
from app.ratelimit import RateLimiter

from . import generation, quota
from .generation import MESSAGE_ANALYSIS_FAILED
from .models import ACTIVE_STATUSES, Analysis, AnalysisStatus
from .schemas import AnalysisErrorOut, AnalysisOut, AnalysisVideoOut

logger = logging.getLogger("app.modules.analysis")

MESSAGE_ANALYSIS_NOT_FOUND = "分析不存在或已失效"
MESSAGE_SUBTITLES_UNAVAILABLE = "该视频没有可用字幕，暂不支持 AI 分析"
MESSAGE_VIDEO_NOT_FOUND = "视频不存在，请重新解析"
MESSAGE_DRM_PROTECTED = "该视频受 DRM 保护，暂不支持 AI 分析"
MESSAGE_MEMBERS_ONLY = "该视频为会员专属内容，暂不支持 AI 分析"
MESSAGE_QUOTA_EXHAUSTED = "今日免费 AI 总结次数已用完，请明天再来"
MESSAGE_BUSY = "服务繁忙，请稍后重试"

_MESSAGE_BY_ERROR_CODE = {
    ErrorCode.ANALYSIS_FAILED.value: MESSAGE_ANALYSIS_FAILED,
}

_MAX_WRITE_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class CreateResult:
    analysis: Analysis
    video: Video | None
    created: bool


def _utc(value: datetime | None) -> datetime | None:
    """SQLite round-trips timezone-aware datetimes as naive UTC values."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    aware = _utc(value)
    return aware.isoformat() if aware is not None else None


def _quota_exhausted(clock: Clock, settings: Settings) -> AppError:
    limit = settings.analysis_daily_quota
    return AppError(
        429,
        ErrorCode.QUOTA_EXHAUSTED,
        MESSAGE_QUOTA_EXHAUSTED,
        {
            "daily_limit": limit,
            "used": limit,
            "remaining": 0,
            "resets_at": quota.next_reset_at(clock).isoformat(),
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


async def _create_once(
    session: AsyncSession,
    clock: Clock,
    settings: Settings,
    *,
    account_id: str,
    video_id: str,
    force: bool,
    rate_limiter: RateLimiter | None = None,
    budget_ledger: BudgetLedger | None = None,
) -> CreateResult:
    video = await session.get(Video, video_id)
    if video is None:
        raise AppError(404, ErrorCode.VIDEO_NOT_FOUND, MESSAGE_VIDEO_NOT_FOUND)
    if video.is_drm:
        raise AppError(403, ErrorCode.DRM_PROTECTED, MESSAGE_DRM_PROTECTED)
    if video.is_members_only:
        raise AppError(403, ErrorCode.MEMBERS_ONLY, MESSAGE_MEMBERS_ONLY)

    subtitle = await session.scalar(select(Subtitle).where(Subtitle.video_id == video_id))
    if subtitle is None:
        raise AppError(
            409,
            ErrorCode.SUBTITLES_UNAVAILABLE,
            MESSAGE_SUBTITLES_UNAVAILABLE,
            {"video_id": video_id},
        )

    active = await _find_active(session, account_id, video_id)
    if active is not None:
        return CreateResult(active, video, False)

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
            return CreateResult(completed, video, False)

    # Gates for a genuinely new Analysis only: reusing an in-progress or completed
    # result above costs neither rate-limit budget nor Quota. Both run before the
    # Quota reservation, so a rejection never consumes Quota.
    if rate_limiter is not None and (
        force or rate_limiter.last_tag("analyses.create", account_id) != video_id
    ):
        # A repeated *non-force* request for the Video that just started is an
        # idempotent retry (double click / two tabs), not a new-analysis attempt.
        rate_limiter.ensure("analyses.create", account_id)
    if budget_ledger is not None:
        await generation.ensure_budget(
            budget_ledger,
            estimated_usd=settings.analysis_cost_per_call_usd,
            clock=clock,
            daily_budget_usd=settings.daily_budget_usd,
        )

    if not await quota.reserve(session, account_id, clock.today(), settings.analysis_daily_quota):
        raise _quota_exhausted(clock, settings)

    now = clock.now()
    analysis = Analysis(
        account_id=account_id,
        video_id=video_id,
        subtitle_id=subtitle.id,
        status=AnalysisStatus.PENDING.value,
        summary_markdown="",
        mindmap_markdown="",
        subtitle_source=subtitle.source_type,
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
        return CreateResult(active, video, False)

    # Only a committed new row consumes the per-Account creation slot; the winner of
    # a concurrent race records here and the loser above never does.
    if rate_limiter is not None:
        rate_limiter.record("analyses.create", account_id, tag=video_id)
    return CreateResult(analysis, video, True)


async def create_analysis(
    session: AsyncSession,
    clock: Clock,
    settings: Settings,
    *,
    account_id: str,
    video_id: str,
    force: bool = False,
    rate_limiter: RateLimiter | None = None,
    budget_ledger: BudgetLedger | None = None,
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


def to_out(analysis: Analysis, video: Video | None) -> AnalysisOut:
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
    )
