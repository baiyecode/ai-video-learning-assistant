"""Filesystem MediaStore (yt-dlp + ffmpeg download). Implemented by tickets #5/#6."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.ports import ResolvedVideo


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
        raise NotImplementedError("FsMediaStore.download is implemented in ticket #5")
