"""Download use-cases: create, read state, retry and open the retained file.

Validation reuses the catalog's 10-minute format snapshot: a Download may only be
created from a fresh resolution, never from stale platform data. All time-sensitive
decisions (URL expiry, file retention) use the injected ``Clock``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.modules.catalog.models import Video
from app.modules.catalog.service import FORMATS_TTL
from app.ports import Clock

from .manager import MESSAGE_DOWNLOAD_FAILED
from .models import Download, DownloadStatus
from .schemas import DownloadErrorOut, DownloadOut
from .signing import SIGNED_URL_TTL, signed_file_path, verify_signature

MAX_RETRIES = 3

_MESSAGE_VIDEO_NOT_FOUND = "视频不存在，请重新解析"
_MESSAGE_FORMATS_EXPIRED = "格式信息已过期，请重新解析该视频"
_MESSAGE_DRM = "该视频受 DRM 保护，本产品不提供绕过 DRM 的解析或下载"
_MESSAGE_MEMBERS_ONLY = "该视频为会员专属内容，本产品不提供绕过会员权限的解析或下载"
_MESSAGE_DOWNLOAD_NOT_FOUND = "下载任务不存在或已过期"
_MESSAGE_NOT_READY = "文件尚未准备完成，请稍候"
_MESSAGE_FILE_EXPIRED = "文件已过期，请重新发起下载"
_MESSAGE_RETRY_IN_PROGRESS = "任务仍在进行中，请稍候再试"
_MESSAGE_RETRY_EXHAUSTED = "重试次数已达上限，请重新发起下载"


async def create_download(
    session: AsyncSession,
    clock: Clock,
    *,
    video_id: str,
    format_id: str,
    visitor_ip: str | None,
    account_id: str | None,
) -> Download:
    """Validate the format snapshot and persist a ``queued`` row (caller re-queues it)."""
    video = await session.get(Video, video_id)
    if video is None:
        raise AppError(404, ErrorCode.VIDEO_NOT_FOUND, _MESSAGE_VIDEO_NOT_FOUND)
    if video.is_drm:
        raise AppError(403, ErrorCode.DRM_PROTECTED, _MESSAGE_DRM)
    if video.is_members_only:
        raise AppError(403, ErrorCode.MEMBERS_ONLY, _MESSAGE_MEMBERS_ONLY)

    fetched_at = _as_aware(video.formats_fetched_at)
    stale = fetched_at is None or clock.now() - fetched_at >= FORMATS_TTL
    known_format = any(
        str(item.get("format_id")) == format_id for item in video.formats_json or []
    )
    if stale or not known_format:
        raise AppError(
            409,
            ErrorCode.FORMATS_EXPIRED,
            _MESSAGE_FORMATS_EXPIRED,
            {"video_id": video.id},
        )

    now = clock.now()
    download = Download(
        video_id=video.id,
        format_id=format_id,
        status=DownloadStatus.QUEUED,
        progress=0.0,
        attempts=0,
        visitor_ip=visitor_ip,
        account_id=account_id,
        created_at=now,
        updated_at=now,
    )
    session.add(download)
    await session.commit()
    return download


async def get_download(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    download_id: str,
) -> DownloadOut:
    """Current task state; ``ready`` tasks get a freshly signed 15-minute URL."""
    download = await _load(session, download_id)
    now = clock.now()

    if download.status == DownloadStatus.EXPIRED:
        raise AppError(410, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)

    if download.status == DownloadStatus.READY:
        file_expires = _as_aware(download.file_expires_at)
        if download.file_path is None or file_expires is None or now >= file_expires:
            await _mark_expired(session, download, now)
            raise AppError(410, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)
        # Keep the link valid while the file is retained, capped at 15 minutes.
        expires_at = min(now + SIGNED_URL_TTL, file_expires)
        download.url_expires_at = expires_at
        await session.commit()
        url = signed_file_path(download.id, int(expires_at.timestamp()), settings.secret_key)
        return to_out(download, download_url=url)

    return to_out(download, download_url=None)


async def prepare_retry(session: AsyncSession, clock: Clock, download_id: str) -> Download:
    """Reset a failed/expired task to ``queued``; manual retries are capped at three."""
    download = await _load(session, download_id)
    if download.status not in {DownloadStatus.FAILED, DownloadStatus.EXPIRED}:
        raise AppError(409, ErrorCode.DOWNLOAD_NOT_READY, _MESSAGE_RETRY_IN_PROGRESS)
    if download.attempts >= MAX_RETRIES:
        raise AppError(409, ErrorCode.DOWNLOAD_FAILED, _MESSAGE_RETRY_EXHAUSTED)

    now = clock.now()
    download.attempts += 1
    download.status = DownloadStatus.QUEUED
    download.progress = 0.0
    download.error_code = None
    download.error_message = None
    download.file_name = None
    download.file_path = None
    download.file_size = None
    download.ready_at = None
    download.url_expires_at = None
    download.file_expires_at = None
    download.updated_at = now
    await session.commit()
    return download


async def resolve_file(
    session: AsyncSession,
    clock: Clock,
    *,
    download_id: str,
    expires_at: int,
    signature: str,
    secret: str,
) -> tuple[Path, str]:
    """Verify the signed URL and return the retained file plus its display name."""
    now = clock.now()
    verify_signature(
        download_id=download_id,
        expires_at=expires_at,
        signature=signature,
        secret=secret,
        now=now,
    )

    download = await _load(session, download_id)
    if download.status == DownloadStatus.EXPIRED:
        raise AppError(403, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)
    if download.status != DownloadStatus.READY:
        raise AppError(409, ErrorCode.DOWNLOAD_NOT_READY, _MESSAGE_NOT_READY)

    file_expires = _as_aware(download.file_expires_at)
    if download.file_path is None or file_expires is None or now >= file_expires:
        await _mark_expired(session, download, now)
        raise AppError(403, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)

    path = Path(download.file_path)
    if not await asyncio.to_thread(path.is_file):
        await _mark_expired(session, download, now)
        raise AppError(403, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)

    return path, download.file_name or path.name


def retry_allowed(download: Download) -> bool:
    return download.status in {DownloadStatus.FAILED, DownloadStatus.EXPIRED} and (
        download.attempts < MAX_RETRIES
    )


async def _load(session: AsyncSession, download_id: str) -> Download:
    download = await session.get(Download, download_id)
    if download is None:
        raise AppError(404, ErrorCode.DOWNLOAD_NOT_FOUND, _MESSAGE_DOWNLOAD_NOT_FOUND)
    return download


async def _mark_expired(session: AsyncSession, download: Download, now: datetime) -> None:
    download.status = DownloadStatus.EXPIRED
    download.updated_at = now
    await session.commit()


def to_out(download: Download, *, download_url: str | None) -> DownloadOut:
    error = None
    if download.error_code and download.status in {DownloadStatus.FAILED, DownloadStatus.EXPIRED}:
        error = DownloadErrorOut(
            code=download.error_code,
            message=download.error_message or MESSAGE_DOWNLOAD_FAILED,
        )
    return DownloadOut(
        id=download.id,
        video_id=download.video_id,
        format_id=download.format_id,
        status=str(download.status),
        progress=float(download.progress or 0.0),
        error=error,
        attempts=int(download.attempts or 0),
        file_name=download.file_name,
        file_size=download.file_size,
        created_at=_required_time(download.created_at),
        updated_at=_required_time(download.updated_at),
        ready_at=_as_aware(download.ready_at),
        download_url=download_url,
        url_expires_at=_as_aware(download.url_expires_at),
        file_expires_at=_as_aware(download.file_expires_at),
        can_retry=retry_allowed(download),
    )


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite round-trips timezone-aware datetimes as naive UTC values."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _required_time(value: datetime | None) -> datetime:
    return _as_aware(value) or datetime.now(UTC)
