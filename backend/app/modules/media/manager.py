"""In-process Download queue and worker.

The manager lives on ``app.state.download_manager`` (created lazily by the router, so
``main.py`` stays untouched). One FIFO worker executes jobs sequentially; ticket #6
adds the global/visitor/account concurrency limits on top of this seam.

Progress callbacks are synchronous by port contract, so they push onto an asyncio
queue drained by a small "pump" coroutine that persists status/progress. The worker
drains the pump before writing the terminal row, which keeps ``ready``/``failed``
from being overwritten by a late ``merging`` update.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.container import Adapters
from app.errors import AppError, ErrorCode
from app.modules.catalog.models import Video
from app.ports import ResolvedVideo, VideoFormat

from .models import Download, DownloadStatus
from .signing import FILE_TTL, SIGNED_URL_TTL

logger = logging.getLogger("app.modules.media")

MESSAGE_DOWNLOAD_FAILED = "下载失败，请稍后重试"
_MESSAGE_TIMEOUT = "下载超时，请稍后重试"
_MESSAGE_VIDEO_GONE = "视频信息不存在，请重新解析后再试"
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_STEM_LENGTH = 80


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
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def submit(self, download_id: str) -> None:
        """Queue a ``queued`` Download and make sure the worker is running."""
        self._queue.put_nowait(download_id)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="download-worker")

    async def wait_idle(self) -> None:
        """Resolve once every submitted Download has reached a terminal state."""
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            try:
                download_id = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                self._worker = None
                return
            try:
                await self._execute(download_id)
            except Exception:  # noqa: BLE001 - one bad job must not kill the queue
                logger.exception(
                    "download_job_crashed",
                    extra={"event": "download_job_crashed", "download_id": download_id},
                )
            finally:
                self._queue.task_done()

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

    async def _mark_failed(self, session: AsyncSession, download: Download, message: str) -> None:
        now = self._clock.now()
        download.status = DownloadStatus.FAILED
        download.error_code = ErrorCode.DOWNLOAD_FAILED.value
        download.error_message = message
        download.updated_at = now
        await session.commit()
        logger.warning(
            "download_failed",
            extra={"event": "download_failed", "download_id": download.id, "code": download.error_code},
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
        return _MESSAGE_TIMEOUT
    if isinstance(error, AppError):
        return error.message
    return MESSAGE_DOWNLOAD_FAILED
