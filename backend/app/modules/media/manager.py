"""In-process Download dispatcher and worker pool.

The manager lives on ``app.state.download_manager`` and is started by the application
lifespan, so restart recovery happens before the first request instead of lazily on
the first Download. A single dispatcher drains a FIFO waiting list and
launches one worker per job while the global, per-Account and per-visitor-IP caps
allow. Work over a cap *waits*; it never fails. The hourly visitor creation cap is
the only rejecting limit and lives in the service layer.

Progress callbacks are synchronous by port contract, so they push onto an asyncio
queue drained by a small "pump" coroutine that persists status/progress. The worker
drains the pump before writing the terminal row, which keeps ``ready``/``failed``
from being overwritten by a late ``merging`` update.

``wait_idle()`` resolves when the waiting list and all workers are empty, which makes
tests deterministic without sleeping. ``cleanup_expired()`` is public so tests can
advance the ``Clock`` instead of waiting for the periodic task.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import messages
from app.config import Settings
from app.container import Adapters
from app.errors import AppError, ErrorCode
from app.formatting import format_file_size
from app.modules.catalog.models import Video
from app.ports import ResolvedVideo, VideoFormat
from app.timeutil import as_utc

from .models import Download, DownloadStatus
from .signing import FILE_TTL, SIGNED_URL_TTL

logger = logging.getLogger("app.modules.media")

_MESSAGE_VIDEO_GONE = "视频信息不存在，请重新解析后再试"
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_STEM_LENGTH = 80


@dataclass(frozen=True, slots=True)
class _Job:
    """Queue entry. Ownership is captured at submit time so caps need no DB reads."""

    download_id: str
    account_id: str | None
    visitor_ip: str | None


class DownloadManager:
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
        self._clock = adapters.clock

        self._max_global = settings.download_global_concurrency
        self._max_account = settings.download_account_concurrency
        self._max_visitor = settings.download_visitor_concurrency

        self._pending: deque[_Job] = deque()
        self._active: dict[str, _Job] = {}
        self._dispatcher: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()

        self._started = False
        self._start_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ lifecycle

    async def start(self, *, exclude_ids: Collection[str] = ()) -> None:
        """Idempotent lazy startup.

        ``exclude_ids`` are rows the caller has *just* created or re-queued; they must
        not be mistaken for work interrupted by a previous process.
        """
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            await self._recover_interrupted(exclude_ids)
            self._started = True
            interval = self._settings.download_cleanup_interval_seconds
            if interval > 0:
                self._cleanup_task = asyncio.create_task(
                    self._cleanup_loop(interval), name="download-cleanup"
                )

    async def stop(self) -> None:
        """Cancel background tasks; generation/download rows stay for recovery."""
        tasks = [task for task in (self._cleanup_task, self._dispatcher) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._cleanup_task = None
        self._dispatcher = None

    async def _recover_interrupted(self, exclude_ids: Collection[str]) -> None:
        """Rows still active at startup belong to a previous process; fail them."""
        now = self._clock.now()
        stmt = (
            update(Download)
            .where(Download.status.in_(_ACTIVE_STATUS_VALUES))
            .values(
                status=DownloadStatus.FAILED.value,
                error_code=ErrorCode.DOWNLOAD_FAILED.value,
                error_message=messages.DOWNLOAD_INTERRUPTED,
                updated_at=now,
            )
        )
        if exclude_ids:
            stmt = stmt.where(Download.id.not_in(exclude_ids))
        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            await session.commit()
        count = result.rowcount or 0
        if count:
            logger.warning(
                "downloads_recovered_after_restart",
                extra={"event": "downloads_recovered_after_restart", "count": count},
            )

    def submit(
        self,
        download_id: str,
        *,
        account_id: str | None = None,
        visitor_ip: str | None = None,
    ) -> None:
        """Queue a ``queued`` Download; the dispatcher starts automatically."""
        self._pending.append(
            _Job(download_id=download_id, account_id=account_id, visitor_ip=visitor_ip)
        )
        self._idle.clear()
        self._wake.set()
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(self._dispatch(), name="download-dispatcher")

    async def wait_idle(self) -> None:
        """Resolve once every submitted Download has reached a terminal state."""
        await self.start()
        await self._idle.wait()

    def queue_position(self, download_id: str) -> int | None:
        """1-based FIFO position for a waiting job; ``None`` while running or unknown."""
        for position, job in enumerate(self._pending, start=1):
            if job.download_id == download_id:
                return position
        return None

    # ------------------------------------------------------------------ dispatcher

    async def _dispatch(self) -> None:
        try:
            while True:
                job = self._next_runnable()
                while job is not None:
                    self._pending.remove(job)
                    self._active[job.download_id] = job
                    asyncio.create_task(
                        self._run_job(job), name=f"download-{job.download_id}"
                    )
                    job = self._next_runnable()
                self._wake.clear()
                if not self._pending and not self._active:
                    self._idle.set()
                    return
                await self._wake.wait()
        finally:
            self._dispatcher = None

    def _next_runnable(self) -> _Job | None:
        """First waiting job whose owner still has a slot; keeps creation order."""
        if len(self._active) >= self._max_global:
            return None
        for job in self._pending:
            if job.account_id is not None:
                if self._count_owner(account_id=job.account_id) >= self._max_account:
                    continue
            elif job.visitor_ip is not None:
                if self._count_owner(visitor_ip=job.visitor_ip) >= self._max_visitor:
                    continue
            return job
        return None

    def _count_owner(self, *, account_id: str | None = None, visitor_ip: str | None = None) -> int:
        if account_id is not None:
            return sum(1 for job in self._active.values() if job.account_id == account_id)
        return sum(
            1
            for job in self._active.values()
            if job.account_id is None and job.visitor_ip == visitor_ip
        )

    async def _run_job(self, job: _Job) -> None:
        try:
            await self._execute(job.download_id)
        except Exception:  # noqa: BLE001 - one bad job must not kill the pool
            logger.exception(
                "download_job_crashed",
                extra={"event": "download_job_crashed", "download_id": job.download_id},
            )
        finally:
            self._active.pop(job.download_id, None)
            self._wake.set()

    # ------------------------------------------------------------------ execution

    async def _execute(self, download_id: str) -> None:
        async with self._sessionmaker() as session:
            download = await session.get(Download, download_id)
            if download is None or download.status != DownloadStatus.QUEUED:
                return
            video = await session.get(Video, download.video_id)
            if video is None:
                await self._mark_failed(session, download, _MESSAGE_VIDEO_GONE)
                return

            download.status = DownloadStatus.DOWNLOADING
            download.progress = 0.0
            download.error_code = None
            download.error_message = None
            download.updated_at = self._clock.now()
            await session.commit()

            updates: asyncio.Queue[tuple[str, float] | None] = asyncio.Queue()
            pump = asyncio.create_task(
                self._pump_progress(download_id, updates), name=f"download-progress-{download_id}"
            )

            def on_progress(phase: str, progress: float) -> None:
                if phase not in {"downloading", "merging"}:
                    return
                try:
                    value = float(progress)
                except (TypeError, ValueError):
                    value = 0.0
                updates.put_nowait((phase, min(1.0, max(0.0, value))))

            path: Path | None = None
            failure: Exception | None = None
            try:
                path = await self._adapters.media_store.download(
                    video=_resolved_video(video),
                    format_id=download.format_id,
                    dest_dir=self._settings.media_dir / download.id,
                    on_progress=on_progress,
                )
            except asyncio.CancelledError:
                updates.put_nowait(None)
                pump.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - any adapter failure becomes download_failed
                failure = exc
            finally:
                updates.put_nowait(None)
            await pump

            if failure is not None or path is None:
                await self._mark_failed(session, download, _failure_message(failure))
                return

            await self._mark_ready(session, download, video, path)

    async def _pump_progress(
        self,
        download_id: str,
        updates: asyncio.Queue[tuple[str, float] | None],
    ) -> None:
        async with self._sessionmaker() as session:
            while True:
                item = await updates.get()
                if item is None:
                    return
                phase, progress = item
                download = await session.get(Download, download_id)
                if download is None:
                    return
                download.status = phase
                download.progress = progress
                download.updated_at = self._clock.now()
                await session.commit()

    async def _mark_ready(
        self,
        session: AsyncSession,
        download: Download,
        video: Video,
        path: Path,
    ) -> None:
        size = (await asyncio.to_thread(path.stat)).st_size
        max_size = self._settings.download_max_file_size_bytes
        if size > max_size:
            await asyncio.to_thread(_remove_file, path, self._settings.media_dir)
            await self._mark_failed(
                session,
                download,
                f"文件大小超过 {format_file_size(max_size)} 上限，无法下载",
                code=ErrorCode.DOWNLOAD_TOO_LARGE,
            )
            return

        ready_at = self._clock.now()
        download.status = DownloadStatus.READY
        download.progress = 1.0
        download.file_path = str(path)
        download.file_name = _file_name(video.title, path)
        download.file_size = size
        download.ready_at = ready_at
        download.url_expires_at = ready_at + SIGNED_URL_TTL
        download.file_expires_at = ready_at + FILE_TTL
        download.updated_at = ready_at
        await session.commit()
        logger.info(
            "download_ready",
            extra={"event": "download_ready", "download_id": download.id, "size": size},
        )

    async def _mark_failed(
        self,
        session: AsyncSession,
        download: Download,
        message: str,
        *,
        code: ErrorCode = ErrorCode.DOWNLOAD_FAILED,
    ) -> None:
        now = self._clock.now()
        download.status = DownloadStatus.FAILED
        download.error_code = code.value
        download.error_message = message
        download.updated_at = now
        await session.commit()
        logger.warning(
            "download_failed",
            extra={"event": "download_failed", "download_id": download.id, "code": download.error_code},
        )

    # -------------------------------------------------------------------- retention

    async def cleanup_expired(self) -> int:
        """Delete files past their retention window and mark their tasks ``expired``."""
        now = self._clock.now()
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(Download).where(Download.status == DownloadStatus.READY)
                )
            ).all()
            expired = [
                row
                for row in rows
                if (expires := as_utc(row.file_expires_at)) is not None and expires <= now
            ]
            for download in expired:
                if download.file_path:
                    await asyncio.to_thread(
                        _remove_file, Path(download.file_path), self._settings.media_dir
                    )
                download.status = DownloadStatus.EXPIRED
                download.file_path = None
                download.updated_at = now
            if expired:
                await session.commit()
        if expired:
            logger.info(
                "downloads_expired",
                extra={"event": "downloads_expired", "count": len(expired)},
            )
        return len(expired)

    async def _cleanup_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.cleanup_expired()
                except Exception:  # noqa: BLE001 - cleanup must not die on one bad row
                    logger.exception("download_cleanup_failed", extra={"event": "download_cleanup_failed"})
        except asyncio.CancelledError:
            raise


_ACTIVE_STATUS_VALUES = tuple(
    status.value for status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.MERGING)
)


def _resolved_video(video: Video) -> ResolvedVideo:
    """Rebuild the port's snapshot from the DB so a stale platform URL is never used."""
    formats = tuple(
        VideoFormat(
            format_id=str(item["format_id"]),
            label=str(item.get("label") or ""),
            ext=str(item.get("ext") or "mp4"),
            width=item.get("width"),
            height=item.get("height"),
            filesize=item.get("filesize"),
            has_video=bool(item.get("has_video", True)),
            has_audio=bool(item.get("has_audio", True)),
        )
        for item in (video.formats_json or [])
        if item.get("format_id")
    )
    return ResolvedVideo(
        platform=video.platform,
        platform_video_id=video.platform_video_id,
        title=video.title,
        duration_seconds=video.duration_seconds,
        webpage_url=video.webpage_url,
        uploader=video.uploader,
        thumbnail_url=video.thumbnail_url,
        formats=formats,
        is_drm=video.is_drm,
        is_members_only=video.is_members_only,
    )


def _file_name(title: str, path: Path) -> str:
    stem = _UNSAFE_FILENAME_CHARS.sub("_", title).strip(" .")[:_MAX_STEM_LENGTH]
    return f"{stem or 'video'}{path.suffix or '.mp4'}"


def _failure_message(error: Exception | None) -> str:
    if isinstance(error, TimeoutError):
        return messages.DOWNLOAD_TIMEOUT
    if isinstance(error, AppError):
        return error.message
    return messages.DOWNLOAD_FAILED


def _remove_file(path: Path, root: Path) -> None:
    """Delete a retained file and, when empty, its per-download directory under ``root``."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "download_file_delete_failed",
            extra={"event": "download_file_delete_failed", "path": str(path)},
        )
        return
    parent = path.parent
    try:
        if parent != root and root in parent.parents:
            parent.rmdir()  # only succeeds when the directory is empty
    except OSError:
        pass


