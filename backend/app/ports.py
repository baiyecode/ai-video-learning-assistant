"""Ports (Protocols) and their data carriers.

Business modules depend on these ports only. Concrete SDK usage (yt-dlp, DeepSeek,
filesystem, system clock) lives in ``app.adapters`` and is wired in ``app.container``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

ProgressCallback = Callable[[str, float], None]
"""``on_progress(phase, progress)`` where phase is ``"downloading"`` or ``"merging"``."""


@dataclass(frozen=True, slots=True)
class VideoFormat:
    """One downloadable format offered by a Platform."""

    format_id: str
    label: str
    ext: str
    width: int | None = None
    height: int | None = None
    filesize: int | None = None
    has_video: bool = True
    has_audio: bool = True


@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    language: str
    name: str
    is_automatic: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedVideo:
    """Platform-normalised identity plus a point-in-time snapshot of formats/subtitles."""

    platform: str
    platform_video_id: str
    title: str
    duration_seconds: int
    webpage_url: str
    uploader: str | None = None
    thumbnail_url: str | None = None
    formats: tuple[VideoFormat, ...] = ()
    subtitles: tuple[SubtitleTrack, ...] = ()
    is_drm: bool = False
    is_members_only: bool = False

    @property
    def video_key(self) -> str:
        return f"{self.platform}:{self.platform_video_id}"


class VideoUnavailableError(Exception):
    """The Platform recognised the URL but the Video cannot be served (private/deleted)."""


@dataclass(frozen=True, slots=True)
class SubtitlePayload:
    """A subtitle track fetched from a Platform, stored as normalised cues and plain text."""

    track: SubtitleTrack
    cues: list[tuple[float, float, str]] = field(default_factory=list)
    text: str = ""


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC instant."""
        ...

    def today(self) -> date:
        """Calendar date in Asia/Shanghai."""
        ...


@runtime_checkable
class VideoSource(Protocol):
    async def resolve(self, url: str) -> ResolvedVideo: ...

    async def fetch_subtitle(self, video: ResolvedVideo, track: SubtitleTrack) -> SubtitlePayload: ...


@runtime_checkable
class MediaStore(Protocol):
    async def download(
        self,
        *,
        video: ResolvedVideo,
        format_id: str,
        dest_dir: Path,
        on_progress: ProgressCallback,
    ) -> Path: ...


@runtime_checkable
class Summarizer(Protocol):
    def stream(self, *, prompt: str) -> AsyncIterator[str]:
        """Yield generated text chunks; the caller consumes it with ``async for``."""
        ...


@runtime_checkable
class BudgetLedger(Protocol):
    async def can_spend(self, estimated_usd: float) -> bool: ...

    async def record(self, usd: float) -> None: ...


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    """A single plain-text email to deliver. The body carries any links the product needs."""

    to: str
    subject: str
    body: str


@runtime_checkable
class EmailSender(Protocol):
    """Deliver one email. Fake adapters keep an observable in-memory inbox."""

    async def send(self, message: OutboundEmail) -> None: ...
