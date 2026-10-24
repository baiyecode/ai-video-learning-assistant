"""Filesystem MediaStore: yt-dlp download + ffmpeg merge into a temp directory.

The executable is resolved at call time (never imported), stdout is parsed for
``[download] nn%`` progress and merge markers, and the produced media file is the
largest file with a known media suffix in the destination directory.

Limits, concurrency and cleanup are owned by ticket #6; this adapter only performs
one download attempt and maps failures to stable ``AppError`` codes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from app import messages
from app.config import Settings
from app.errors import AppError, ErrorCode
from app.ports import ResolvedVideo

logger = logging.getLogger("app.adapters.fs_media")

_DOWNLOAD_TIMEOUT_SECONDS = 30 * 60
_PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
_MERGE_MARKERS = ("[Merger]", "[ffmpeg]")
_MEDIA_SUFFIXES = frozenset({".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3"})

_MESSAGE_UNAVAILABLE = "下载服务暂时不可用，请稍后再试"


class FsMediaStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def download(
        self,
        *,
        video: ResolvedVideo,
        format_id: str,
        dest_dir: Path,
        on_progress: Callable[[str, float], None],
    ) -> Path:
        destination = Path(dest_dir)
        await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)

        executable = shutil.which("yt-dlp")
        if executable is None:
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_UNAVAILABLE)

        args = [
            executable,
            "--no-playlist",
            "--no-warnings",
            "--newline",
            "--progress",
            "--no-simulate",
            "--merge-output-format",
            "mp4",
            "-f",
            format_id,
            "-o",
            str(destination / "media.%(ext)s"),
            video.webpage_url,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            logger.warning("ytdlp_spawn_failed", extra={"event": "ytdlp_spawn_failed"})
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_UNAVAILABLE) from exc

        try:
            async with asyncio.timeout(_DOWNLOAD_TIMEOUT_SECONDS):
                await _stream_progress(process, on_progress)
                returncode = await process.wait()
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AppError(504, ErrorCode.DOWNLOAD_FAILED, messages.DOWNLOAD_TIMEOUT) from exc

        if returncode != 0:
            logger.warning(
                "ytdlp_download_failed",
                extra={"event": "ytdlp_download_failed", "returncode": returncode},
            )
            raise AppError(502, ErrorCode.DOWNLOAD_FAILED, messages.DOWNLOAD_FAILED)

        on_progress("merging", 1.0)
        return await asyncio.to_thread(_largest_media_file, destination)


async def _stream_progress(
    process: asyncio.subprocess.Process,
    on_progress: Callable[[str, float], None],
) -> None:
    assert process.stdout is not None
    while True:
        raw = await process.stdout.readline()
        if not raw:
            return
        line = raw.decode("utf-8", errors="replace")
        match = _PROGRESS_RE.search(line)
        if match is not None:
            on_progress("downloading", min(1.0, max(0.0, float(match.group(1)) / 100)))
        elif any(marker in line for marker in _MERGE_MARKERS):
            on_progress("merging", 0.0)


def _largest_media_file(directory: Path) -> Path:
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in _MEDIA_SUFFIXES
    ]
    if not candidates:
        raise AppError(502, ErrorCode.DOWNLOAD_FAILED, messages.DOWNLOAD_FAILED)
    return max(candidates, key=lambda path: path.stat().st_size)
