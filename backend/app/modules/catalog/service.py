"""Video resolve + cached metadata use-cases.

Identity is owned by the Platform, not by the URL: the input is normalised (tracking
params, timestamps, mobile hosts, short-link wrappers) and the adapter returns the
authoritative ``(platform, platform_video_id)`` pair. Both are upserted into one row.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import messages
from app.config import Settings
from app.errors import AppError, ErrorCode
from app.ports import Clock, ResolvedVideo, VideoSource, VideoUnavailableError
from app.timeutil import as_utc

from . import subtitles
from .models import Video
from .schemas import (
    LEGAL_NOTICE,
    ResolveResponse,
    SubtitleOut,
    VideoDetailResponse,
    VideoFormatOut,
    VideoOut,
    format_snapshot,
    subtitle_snapshot,
)
from .urls import (
    DEFAULT_ENABLED_PLATFORMS,
    DOUYIN_PLATFORM,
    ensure_public_url,
    normalize_video_url,
)

logger = logging.getLogger("app.modules.catalog")

FORMATS_TTL = timedelta(minutes=10)

_MESSAGE_VIDEO_UNAVAILABLE = "视频不可用，可能已被删除、设为私密或受地区限制"


def enabled_platforms(settings: Settings) -> frozenset[str]:
    """The Platform registry as opened by this deployment's feature switches."""
    if settings.douyin_enabled:
        return DEFAULT_ENABLED_PLATFORMS | {DOUYIN_PLATFORM}
    return DEFAULT_ENABLED_PLATFORMS


async def resolve_video(
    session: AsyncSession,
    source: VideoSource,
    clock: Clock,
    raw_url: str,
    settings: Settings,
) -> ResolveResponse:
    platforms = enabled_platforms(settings)
    normalized_url = normalize_video_url(raw_url, enabled_platforms=platforms)
    await ensure_public_url(normalized_url)
    resolved = await _resolve_with_source(source, normalized_url)

    if resolved.is_drm:
        raise AppError(403, ErrorCode.DRM_PROTECTED, messages.DRM_PROTECTED)
    if resolved.is_members_only:
        raise AppError(403, ErrorCode.MEMBERS_ONLY, messages.MEMBERS_ONLY)

    platform = resolved.platform.strip().lower()
    platform_video_id = resolved.platform_video_id.strip()
    if platform not in platforms:
        raise AppError(422, ErrorCode.UNSUPPORTED_URL, messages.UNSUPPORTED_PLATFORM)
    if not platform_video_id:
        raise AppError(502, ErrorCode.RESOLVE_FAILED, messages.RESOLVE_FAILED)

    video = await _upsert_video(
        session,
        resolved=resolved,
        platform=platform,
        platform_video_id=platform_video_id,
        clock=clock,
    )
    has_subtitle = await subtitles.sync_selection(session, source, video, resolved)
    return _resolve_response(video, has_subtitle=has_subtitle)


async def get_video(session: AsyncSession, clock: Clock, video_id: str) -> VideoDetailResponse:
    video = await session.get(Video, video_id)
    if video is None:
        raise AppError(404, ErrorCode.VIDEO_NOT_FOUND, messages.VIDEO_NOT_FOUND)

    fetched_at = as_utc(video.formats_fetched_at)
    if fetched_at is None or clock.now() - fetched_at >= FORMATS_TTL:
        details: dict[str, Any] = {"video_id": video.id}
        if fetched_at is not None:
            details["formats_fetched_at"] = fetched_at.isoformat()
        raise AppError(409, ErrorCode.FORMATS_EXPIRED, messages.FORMATS_EXPIRED, details)

    base = _resolve_response(
        video, has_subtitle=await subtitles.has_subtitle(session, video.id)
    )
    return VideoDetailResponse(
        **base.model_dump(),
        formats_fetched_at=fetched_at,
        formats_expired=False,
    )


async def _resolve_with_source(source: VideoSource, url: str) -> ResolvedVideo:
    try:
        return await source.resolve(url)
    except AppError:
        raise
    except VideoUnavailableError as exc:
        raise AppError(404, ErrorCode.VIDEO_UNAVAILABLE, _MESSAGE_VIDEO_UNAVAILABLE) from exc
    except Exception as exc:  # noqa: BLE001 - any adapter failure becomes a stable code
        logger.warning(
            "video_resolve_failed",
            extra={"event": "video_resolve_failed", "error_type": type(exc).__name__},
        )
        raise AppError(502, ErrorCode.RESOLVE_FAILED, messages.RESOLVE_FAILED) from exc


async def _upsert_video(
    session: AsyncSession,
    *,
    resolved: ResolvedVideo,
    platform: str,
    platform_video_id: str,
    clock: Clock,
) -> Video:
    formats = [format_snapshot(fmt) for fmt in resolved.formats]
    subtitles = [subtitle_snapshot(track) for track in resolved.subtitles]
    fetched_at = clock.now()

    existing = await _find_video(session, platform, platform_video_id)
    if existing is not None:
        _apply_resolution(existing, resolved, formats, subtitles, fetched_at)
        await session.commit()
        return existing

    video = Video(
        id=uuid4().hex,
        platform=platform,
        platform_video_id=platform_video_id,
        formats_json=formats,
        subtitles_json=subtitles,
        formats_fetched_at=fetched_at,
    )
    _apply_resolution(video, resolved, formats, subtitles, fetched_at)
    session.add(video)
    try:
        await session.commit()
        return video
    except IntegrityError:
        # A concurrent resolve inserted the same identity first: adopt that row.
        await session.rollback()
        existing = await _find_video(session, platform, platform_video_id)
        if existing is None:
            raise
        _apply_resolution(existing, resolved, formats, subtitles, fetched_at)
        await session.commit()
        return existing


async def _find_video(session: AsyncSession, platform: str, platform_video_id: str) -> Video | None:
    stmt = select(Video).where(
        Video.platform == platform,
        Video.platform_video_id == platform_video_id,
    )
    return await session.scalar(stmt)


def _apply_resolution(
    video: Video,
    resolved: ResolvedVideo,
    formats: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    fetched_at: datetime,
) -> None:
    video.title = resolved.title
    video.duration_seconds = resolved.duration_seconds
    video.webpage_url = resolved.webpage_url
    video.uploader = resolved.uploader
    video.thumbnail_url = resolved.thumbnail_url
    video.is_drm = resolved.is_drm
    video.is_members_only = resolved.is_members_only
    video.formats_json = formats
    video.subtitles_json = subtitles
    video.formats_fetched_at = fetched_at


def _resolve_response(video: Video, *, has_subtitle: bool) -> ResolveResponse:
    formats = [VideoFormatOut.from_snapshot(item) for item in video.formats_json or []]
    subtitles = [SubtitleOut.from_snapshot(item) for item in video.subtitles_json or []]
    return ResolveResponse(
        video=VideoOut(
            id=video.id,
            platform=video.platform,
            platform_video_id=video.platform_video_id,
            title=video.title,
            duration_seconds=video.duration_seconds,
            webpage_url=video.webpage_url,
            uploader=video.uploader,
            thumbnail_url=video.thumbnail_url,
            is_drm=video.is_drm,
            is_members_only=video.is_members_only,
        ),
        formats=formats,
        subtitles=subtitles,
        can_analyze=has_subtitle and not video.is_drm and not video.is_members_only,
        resolve_notice=LEGAL_NOTICE,
    )
