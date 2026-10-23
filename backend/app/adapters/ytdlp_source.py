"""yt-dlp backed VideoSource. Implemented by ticket #3 (Video resolve)."""

from __future__ import annotations

from app.config import Settings
from app.ports import ResolvedVideo, SubtitlePayload, SubtitleTrack


class YtDlpVideoSource:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def resolve(self, url: str) -> ResolvedVideo:
        raise NotImplementedError("YtDlpVideoSource.resolve is implemented in ticket #3")

    async def fetch_subtitle(self, video: ResolvedVideo, track: SubtitleTrack) -> SubtitlePayload:
        raise NotImplementedError("YtDlpVideoSource.fetch_subtitle is implemented in ticket #4")
