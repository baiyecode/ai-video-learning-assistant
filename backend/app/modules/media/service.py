"""Download use-cases: create, read state, retry and open the retained file.

Validation reuses the catalog's 10-minute format snapshot: a Download may only be
created from a fresh resolution, never from stale platform data. All time-sensitive
decisions (URL expiry, file retention) use the injected ``Clock``.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.formatting import format_file_size
from app.modules.catalog.models import Video
from app.modules.catalog.service import FORMATS_TTL
from app.ports import Clock
from app.timeutil import as_utc, required_utc

from .manager import MESSAGE_DOWNLOAD_FAILED
from .models import Download, DownloadStatus
from .schemas import DownloadErrorOut, DownloadOut
from .signing import SIGNED_URL_TTL, signed_file_path, verify_signature

MAX_RETRIES = 3
VISITOR_WINDOW = timedelta(hours=1)

_MESSAGE_VIDEO_NOT_FOUND = "视频不存在，请重新解析"
_MESSAGE_FORMATS_EXPIRED = "格式信息已过期，请重新解析该视频"
_MESSAGE_DRM = "该视频受 DRM 保护，本产品不提供绕过 DRM 的解析或下载"
_MESSAGE_MEMBERS_ONLY = "该视频为会员专属内容，本产品不提供绕过会员权限的解析或下载"
_MESSAGE_DOWNLOAD_NOT_FOUND = "下载任务不存在或已过期"
_MESSAGE_NOT_READY = "文件尚未准备完成，请稍候"
_MESSAGE_FILE_EXPIRED = "文件已过期，请重新发起下载"
_MESSAGE_RETRY_IN_PROGRESS = "任务仍在进行中，请稍候再试"
_MESSAGE_RETRY_EXHAUSTED = "重试已达上限，请重新发起下载"


async def create_download(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    *,
    video_id: str,
    format_id: str,
    visitor_ip: str | None,
    account_id: str | None,
) -> Download:
    """Validate the format snapshot and persist a ``queued`` row (caller re-queues it).

    Resource boundaries are enforced before inserting anything: a Video longer than
    ``download_max_duration_seconds`` or a format whose known size exceeds
    ``download_max_file_size_bytes`` is rejected outright. The per-IP hourly cap is
    the only limit that rejects with ``download_limit_reached``; concurrency caps
    waiting elsewhere in the queue.
    """
    video = await session.get(Video, video_id)
    if video is None:
        raise AppError(404, ErrorCode.VIDEO_NOT_FOUND, _MESSAGE_VIDEO_NOT_FOUND)
    if video.is_drm:
        raise AppError(403, ErrorCode.DRM_PROTECTED, _MESSAGE_DRM)
    if video.is_members_only:
        raise AppError(403, ErrorCode.MEMBERS_ONLY, _MESSAGE_MEMBERS_ONLY)

    max_duration = settings.download_max_duration_seconds
    if video.duration_seconds > max_duration:
        raise AppError(
            422,
            ErrorCode.DOWNLOAD_TOO_LONG,
            _too_long_message(max_duration),
            {"duration_seconds": video.duration_seconds, "max_duration_seconds": max_duration},
        )

    fetched_at = as_utc(video.formats_fetched_at)
    stale = fetched_at is None or clock.now() - fetched_at >= FORMATS_TTL
    known_format = next(
        (
            item
            for item in video.formats_json or []
            if str(item.get("format_id")) == format_id
        ),
        None,
    )
    if stale or known_format is None:
        raise AppError(
            409,
            ErrorCode.FORMATS_EXPIRED,
            _MESSAGE_FORMATS_EXPIRED,
            {"video_id": video.id},
        )

    max_size = settings.download_max_file_size_bytes
    filesize = _known_filesize(known_format.get("filesize"))
    if filesize is not None and filesize > max_size:
        raise AppError(
            422,
            ErrorCode.DOWNLOAD_TOO_LARGE,
            _too_large_message(max_size),
            {"filesize": filesize, "max_file_size_bytes": max_size},
        )

    now = clock.now()
    if account_id is None and visitor_ip is not None:
        await _enforce_visitor_hourly_cap(
            session,
            settings,
            visitor_ip=visitor_ip,
            now=now,
        )

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


async def _enforce_visitor_hourly_cap(
    session: AsyncSession,
    settings: Settings,
    *,
    visitor_ip: str,
    now: datetime,
) -> None:
    """Visitors may create at most ``download_visitor_hourly_limit`` tasks per hour per IP."""
    cutoff = now - VISITOR_WINDOW
    recent = (
        await session.scalars(
            select(Download).where(
                Download.account_id.is_(None),
                Download.visitor_ip == visitor_ip,
                Download.created_at > cutoff,
            )
        )
    ).all()
    limit = settings.download_visitor_hourly_limit
    if len(recent) < limit:
        return

    oldest = min(as_utc(row.created_at) or now for row in recent)
    reset_at = oldest + VISITOR_WINDOW
    retry_after = max(1, math.ceil((reset_at - now).total_seconds()))
    raise AppError(
        429,
        ErrorCode.DOWNLOAD_LIMIT_REACHED,
        f"访客每小时最多发起 {limit} 个 Download，请稍后再试或登录后下载",
        {"retry_after": retry_after, "reset_at": reset_at.isoformat(), "limit": limit},
    )


async def get_download(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    download_id: str,
    *,
    account_id: str | None = None,
    visitor_ip: str | None = None,
) -> DownloadOut:
    """Current task state; ``ready`` tasks get a freshly signed 15-minute URL.

    Account-owned Downloads are only visible to that Account; Visitor Downloads only
    to the same ``visitor_ip``. A mismatch is indistinguishable from a missing row.
    """
    download = await _load(session, download_id)
    _ensure_owner(download, account_id=account_id, visitor_ip=visitor_ip)
    now = clock.now()

    if download.status == DownloadStatus.EXPIRED:
        raise AppError(410, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)

    if download.status == DownloadStatus.READY:
        file_expires = as_utc(download.file_expires_at)
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


async def prepare_retry(
    session: AsyncSession,
    clock: Clock,
    download_id: str,
    *,
    account_id: str | None = None,
    visitor_ip: str | None = None,
) -> Download:
    """Reset a failed/expired task to ``queued``; manual retries are capped at three."""
    download = await _load(session, download_id)
    _ensure_owner(download, account_id=account_id, visitor_ip=visitor_ip)
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
        raise AppError(410, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)
    if download.status != DownloadStatus.READY:
        raise AppError(409, ErrorCode.DOWNLOAD_NOT_READY, _MESSAGE_NOT_READY)

    file_expires = as_utc(download.file_expires_at)
    if download.file_path is None or file_expires is None or now >= file_expires:
        await _mark_expired(session, download, now)
        raise AppError(410, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)

    path = Path(download.file_path)
    if not await asyncio.to_thread(path.is_file):
        await _mark_expired(session, download, now)
        raise AppError(410, ErrorCode.FILE_EXPIRED, _MESSAGE_FILE_EXPIRED)

    return path, download.file_name or path.name


def retry_allowed(download: Download) -> bool:
    return download.status in {DownloadStatus.FAILED, DownloadStatus.EXPIRED} and (
        download.attempts < MAX_RETRIES
    )


def _known_filesize(value: object) -> int | None:
    """Platform snapshots sometimes omit the size; only a positive known value counts."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    size = int(value)
    return size if size > 0 else None


def _too_long_message(max_duration_seconds: int) -> str:
    hours = max_duration_seconds / 3600
    label = f"{hours:g}"
    return f"视频时长超过 {label} 小时上限，暂不支持下载"


def _too_large_message(max_file_size_bytes: int) -> str:
    return f"文件大小超过 {format_file_size(max_file_size_bytes)} 上限，无法下载"


async def _load(session: AsyncSession, download_id: str) -> Download:
    download = await session.get(Download, download_id)
    if download is None:
        raise AppError(404, ErrorCode.DOWNLOAD_NOT_FOUND, _MESSAGE_DOWNLOAD_NOT_FOUND)
    return download


def _ensure_owner(
    download: Download, *, account_id: str | None, visitor_ip: str | None
) -> None:
    """Reject cross-owner access with the same 404 a missing Download returns."""
    if download.account_id is not None:
        allowed = account_id == download.account_id
    else:
        allowed = account_id is None and visitor_ip == download.visitor_ip
    if not allowed:
        raise AppError(404, ErrorCode.DOWNLOAD_NOT_FOUND, _MESSAGE_DOWNLOAD_NOT_FOUND)


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
        created_at=required_utc(download.created_at),
        updated_at=required_utc(download.updated_at),
        ready_at=as_utc(download.ready_at),
        download_url=download_url,
        url_expires_at=as_utc(download.url_expires_at),
        file_expires_at=as_utc(download.file_expires_at),
        can_retry=retry_allowed(download),
    )
