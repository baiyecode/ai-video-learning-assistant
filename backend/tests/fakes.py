"""Deterministic ports for tests. Extend these, never fork them."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.container import Adapters
from app.ports import ResolvedVideo, SubtitlePayload, SubtitleTrack, VideoFormat

SHANGHAI = ZoneInfo("Asia/Shanghai")


def sample_subtitle_track(language: str = "zh-Hans", *, automatic: bool = False) -> SubtitleTrack:
    return SubtitleTrack(language=language, name="中文（简体）", is_automatic=automatic)


def sample_video(
    *,
    platform: str = "youtube",
    platform_video_id: str = "dQw4w9WgXcQ",
    title: str = "示例视频",
    duration_seconds: int = 300,
) -> ResolvedVideo:
    return ResolvedVideo(
        platform=platform,
        platform_video_id=platform_video_id,
        title=title,
        duration_seconds=duration_seconds,
        webpage_url=f"https://example.com/watch?v={platform_video_id}",
        uploader="示例作者",
        thumbnail_url=None,
        formats=(
            VideoFormat(format_id="bv*+ba/b", label="最佳画质", ext="mp4", height=1080),
            VideoFormat(format_id="bestaudio", label="仅音频", ext="m4a", has_video=False),
        ),
        subtitles=(sample_subtitle_track(),),
    )


@dataclass
class FrozenClock:
    """A Clock frozen at an instant; advance it explicitly in tests."""

    instant: datetime = field(default_factory=lambda: datetime(2026, 1, 15, 8, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.instant

    def today(self) -> date:
        return self.instant.astimezone(SHANGHAI).date()

    def advance(self, *, seconds: float = 0, days: int = 0) -> datetime:
        self.instant = self.instant + timedelta(seconds=seconds, days=days)
        return self.instant


@dataclass
class FakeVideoSource:
    """Resolves URLs from an in-memory catalogue and serves canned subtitles."""

    videos: dict[str, ResolvedVideo] = field(default_factory=dict)
    subtitles: dict[tuple[str, str], SubtitlePayload] = field(default_factory=dict)
    resolve_error: Exception | None = None
    resolve_calls: list[str] = field(default_factory=list)
    subtitle_calls: list[tuple[str, str]] = field(default_factory=list)

    async def resolve(self, url: str) -> ResolvedVideo:
        self.resolve_calls.append(url)
        if self.resolve_error is not None:
            raise self.resolve_error
        if url in self.videos:
            return self.videos[url]
        return sample_video()

    async def fetch_subtitle(self, video: ResolvedVideo, track: SubtitleTrack) -> SubtitlePayload:
        self.subtitle_calls.append((video.platform_video_id, track.language))
        payload = self.subtitles.get((video.platform_video_id, track.language))
        if payload is not None:
            return payload
        return SubtitlePayload(
            track=track,
            cues=[(0.0, 2.0, "示例字幕")],
            text="示例字幕",
        )


@dataclass
class FakeMediaStore:
    """Writes deterministic bytes to dest_dir and reports progress phases."""

    content: bytes = b"fake-media-bytes"
    fail_with: Exception | None = None
    downloads: list[dict[str, object]] = field(default_factory=list)

    async def download(
        self,
        *,
        video: ResolvedVideo,
        format_id: str,
        dest_dir: Path,
        on_progress: Callable[[str, float], None],
    ) -> Path:
        self.downloads.append(
            {"video_id": video.platform_video_id, "format_id": format_id, "dest_dir": dest_dir}
        )
        on_progress("downloading", 0.0)
        if self.fail_with is not None:
            raise self.fail_with
        on_progress("downloading", 0.5)
        on_progress("merging", 1.0)
        dest_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - tiny test file write
        target = Path(dest_dir) / f"{video.platform}-{video.platform_video_id}-{format_id}.mp4"
        target.write_bytes(self.content)  # noqa: ASYNC240
        return target


@dataclass
class FakeSummarizer:
    """Streams scripted chunks; optionally raises on the first iteration."""

    chunks: list[str] = field(default_factory=lambda: ["这是", "一段", "摘要"])
    error: Exception | None = None
    prompts: list[str] = field(default_factory=list)

    def stream(self, *, prompt: str) -> AsyncIterator[str]:
        self.prompts.append(prompt)

        async def _generate() -> AsyncIterator[str]:
            if self.error is not None:
                raise self.error
            for chunk in self.chunks:
                yield chunk

        return _generate()


@dataclass
class FakeBudgetLedger:
    """In-memory daily USD ledger."""

    budget_usd: float = 10.0
    spent_usd: float = 0.0
    recorded: list[float] = field(default_factory=list)

    async def can_spend(self, estimated_usd: float) -> bool:
        return self.spent_usd + estimated_usd <= self.budget_usd

    async def record(self, usd: float) -> None:
        self.spent_usd += usd
        self.recorded.append(usd)


def make_fake_adapters(
    *,
    video_source: FakeVideoSource | None = None,
    media_store: FakeMediaStore | None = None,
    summarizer: FakeSummarizer | None = None,
    clock: FrozenClock | None = None,
    budget_ledger: FakeBudgetLedger | None = None,
) -> Adapters:
    """Build the full Adapters container with fakes. Pass overrides by keyword."""
    return Adapters(
        video_source=video_source or FakeVideoSource(),
        media_store=media_store or FakeMediaStore(),
        summarizer=summarizer or FakeSummarizer(),
        clock=clock or FrozenClock(),
        budget_ledger=budget_ledger or FakeBudgetLedger(),
    )
