"""Subtitle selection, persistence and export for a Video.

Selection rules (product spec, "领域模型"):

1. a manual track always wins over an automatic one;
2. within the same source type the language preference is ``zh-Hans``, ``zh``, ``en``,
   then any other available track (declaration order breaks ties).

Only one Subtitle selection is kept per Video. Its cues are stored normalised and the
plain display text is derived from them, so the SRT/VTT/TXT exports always carry the
same content as the UI.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, ErrorCode
from app.ports import ResolvedVideo, SubtitleTrack, VideoSource

from .models import Subtitle, Video
from .schemas import SubtitleCueOut, SubtitleDetailResponse

logger = logging.getLogger("app.catalog.subtitles")

SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
SubtitleFormat = Literal["srt", "vtt", "txt"]

PREFERRED_LANGUAGES = ("zh-Hans", "zh", "en")

_MESSAGE_VIDEO_NOT_FOUND = "视频不存在，请重新解析"
_MESSAGE_SUBTITLES_UNAVAILABLE = "该视频没有可用字幕，暂不支持 AI 分析"

_MEDIA_TYPES: dict[str, str] = {
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "txt": "text/plain; charset=utf-8",
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class SubtitleExport:
    content: str
    media_type: str
    filename: str


# --------------------------------------------------------------------------- selection


def _language_rank(language: str) -> int | None:
    """Rank a track language against the preference list; ``None`` means "any other"."""
    normalized = language.strip().lower().replace("_", "-")
    for index, preferred in enumerate(PREFERRED_LANGUAGES):
        preferred = preferred.lower()
        if normalized == preferred or normalized.startswith(f"{preferred}-"):
            return index
    return None


def _pick_best(tracks: list[SubtitleTrack]) -> SubtitleTrack | None:
    best: tuple[tuple[int, int, int], SubtitleTrack] | None = None
    for index, track in enumerate(tracks):
        rank = _language_rank(track.language)
        key = (0, rank, index) if rank is not None else (1, 0, index)
        if best is None or key < best[0]:
            best = (key, track)
    return best[1] if best is not None else None


def select_track(tracks: tuple[SubtitleTrack, ...] | list[SubtitleTrack]) -> SubtitleTrack | None:
    """Prefer manual over automatic, then the language preference order."""
    manual = [track for track in tracks if not track.is_automatic]
    chosen = _pick_best(manual)
    if chosen is not None:
        return chosen
    return _pick_best([track for track in tracks if track.is_automatic])


def source_type_of(track: SubtitleTrack) -> str:
    return SOURCE_AUTO if track.is_automatic else SOURCE_MANUAL


# ---------------------------------------------------------------------------- storage


async def _find(session: AsyncSession, video_id: str) -> Subtitle | None:
    return await session.scalar(select(Subtitle).where(Subtitle.video_id == video_id))


def _normalize_text(value: str) -> str:
    return " ".join(str(value).split())


def normalize_cues(cues: list[tuple[float, float, str]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for start, end, text in cues:
        cleaned = _normalize_text(text)
        if not cleaned:
            continue
        start_seconds = max(0.0, float(start))
        end_seconds = max(start_seconds, float(end))
        normalized.append(
            {"start": round(start_seconds, 3), "end": round(end_seconds, 3), "text": cleaned}
        )
    return normalized


async def sync_selection(
    session: AsyncSession,
    source: VideoSource,
    video: Video,
    resolved: ResolvedVideo,
) -> bool:
    """Select and persist the Subtitle for a freshly resolved Video.

    Returns whether a Subtitle is now available. A failing adapter must not break
    Video resolution, so fetch errors are logged and treated as "no Subtitle".
    """
    track = select_track(resolved.subtitles)
    existing = await _find(session, video.id)

    if track is None:
        if existing is not None:
            await session.delete(existing)
            await session.commit()
        return False

    source_type = source_type_of(track)
    if (
        existing is not None
        and existing.language == track.language
        and existing.source_type == source_type
    ):
        return True

    try:
        payload = await source.fetch_subtitle(resolved, track)
        cues = normalize_cues(payload.cues)
        text = "\n".join(cue["text"] for cue in cues) or _normalize_text(payload.text)
    except Exception as exc:  # noqa: BLE001 - subtitle failures must not fail resolve
        logger.warning(
            "subtitle_fetch_failed",
            extra={
                "event": "subtitle_fetch_failed",
                "video_id": video.id,
                "language": track.language,
                "error_type": type(exc).__name__,
            },
        )
        return existing is not None

    if not cues and not text:
        if existing is not None:
            await session.delete(existing)
            await session.commit()
        return False

    row = existing if existing is not None else Subtitle(video_id=video.id)
    row.language = track.language
    row.source_type = source_type
    row.cues_json = cues
    row.text = text
    if existing is None:
        session.add(row)
    await session.commit()
    return True


async def has_subtitle(session: AsyncSession, video_id: str) -> bool:
    stmt = select(Subtitle.id).where(Subtitle.video_id == video_id)
    return await session.scalar(stmt) is not None


async def _require_subtitle(session: AsyncSession, video_id: str) -> tuple[Video, Subtitle]:
    video = await session.get(Video, video_id)
    if video is None:
        raise AppError(404, ErrorCode.VIDEO_NOT_FOUND, _MESSAGE_VIDEO_NOT_FOUND)
    subtitle = await _find(session, video_id)
    if subtitle is None:
        raise AppError(
            409,
            ErrorCode.SUBTITLES_UNAVAILABLE,
            _MESSAGE_SUBTITLES_UNAVAILABLE,
            {"video_id": video_id},
        )
    return video, subtitle


async def get_subtitle(session: AsyncSession, video_id: str) -> SubtitleDetailResponse:
    _, subtitle = await _require_subtitle(session, video_id)
    return SubtitleDetailResponse(
        language=subtitle.language,
        source_type=subtitle.source_type,  # type: ignore[arg-type]
        text=subtitle.text,
        cues=[SubtitleCueOut(**cue) for cue in subtitle.cues_json or []],
        can_analyze=True,
    )


# ---------------------------------------------------------------------------- exports


def format_timestamp(seconds: float, *, separator: str = ",") -> str:
    """Format seconds as ``HH:MM:SS<sep>mmm`` (SRT uses ``,``, VTT uses ``.``)."""
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1_000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
    )


def render_srt(cues: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        timing = (
            f"{format_timestamp(cue['start'])} --> {format_timestamp(cue['end'])}"
        )
        blocks.append(f"{index}\n{timing}\n{cue['text']}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_vtt(cues: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for cue in cues:
        timing = (
            f"{format_timestamp(cue['start'], separator='.')} --> "
            f"{format_timestamp(cue['end'], separator='.')}"
        )
        blocks.append(f"{timing}\n{cue['text']}")
    return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def export_filename(video: Video, fmt: str) -> str:
    stem = _UNSAFE_FILENAME_CHARS.sub(
        "_", f"{video.platform}-{video.platform_video_id}"
    ).strip("._-")
    return f"{stem or video.id}.{fmt}"


async def export_subtitle(
    session: AsyncSession, video_id: str, fmt: SubtitleFormat
) -> SubtitleExport:
    video, subtitle = await _require_subtitle(session, video_id)
    cues = subtitle.cues_json or []
    if fmt == "srt":
        content = render_srt(cues)
    elif fmt == "vtt":
        content = render_vtt(cues)
    else:
        content = subtitle.text
    return SubtitleExport(
        content=content,
        media_type=_MEDIA_TYPES[fmt],
        filename=export_filename(video, fmt),
    )
