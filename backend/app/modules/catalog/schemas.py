"""Pydantic request/response schemas for the catalog HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ports import SubtitleTrack, VideoFormat

LEGAL_NOTICE = "仅限个人备份或已获授权内容"
# Surfaced wherever a Download's lifecycle is described so the copy stays identical.
RETENTION_NOTICE = "临时文件将在 1 小时后自动删除"


class ResolveVideoRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class VideoFormatOut(BaseModel):
    format_id: str
    label: str
    ext: str
    resolution: str
    width: int | None = None
    height: int | None = None
    filesize: int | None = None
    has_video: bool = True
    has_audio: bool = True

    @classmethod
    def from_port(cls, fmt: VideoFormat) -> VideoFormatOut:
        return cls(
            format_id=fmt.format_id,
            label=fmt.label,
            ext=fmt.ext,
            resolution=_resolution_label(fmt),
            width=fmt.width,
            height=fmt.height,
            filesize=fmt.filesize,
            has_video=fmt.has_video,
            has_audio=fmt.has_audio,
        )

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> VideoFormatOut:
        return cls(
            format_id=str(data["format_id"]),
            label=str(data.get("label") or ""),
            ext=str(data.get("ext") or ""),
            resolution=str(data.get("resolution") or ""),
            width=data.get("width"),
            height=data.get("height"),
            filesize=data.get("filesize"),
            has_video=bool(data.get("has_video", True)),
            has_audio=bool(data.get("has_audio", True)),
        )

    def to_snapshot(self) -> dict[str, Any]:
        return self.model_dump()


class SubtitleOut(BaseModel):
    language: str
    name: str
    is_automatic: bool = False

    @classmethod
    def from_port(cls, track: SubtitleTrack) -> SubtitleOut:
        return cls(language=track.language, name=track.name, is_automatic=track.is_automatic)

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> SubtitleOut:
        return cls(
            language=str(data["language"]),
            name=str(data.get("name") or data["language"]),
            is_automatic=bool(data.get("is_automatic", False)),
        )


class VideoOut(BaseModel):
    id: str
    platform: str
    platform_video_id: str
    title: str
    duration_seconds: int
    webpage_url: str
    uploader: str | None = None
    thumbnail_url: str | None = None
    is_drm: bool = False
    is_members_only: bool = False


class ResolveResponse(BaseModel):
    video: VideoOut
    formats: list[VideoFormatOut]
    subtitles: list[SubtitleOut]
    can_analyze: bool
    resolve_notice: str
    retention_notice: str = RETENTION_NOTICE


class VideoDetailResponse(ResolveResponse):
    formats_fetched_at: datetime
    formats_expired: bool = False


class SubtitleCueOut(BaseModel):
    start: float
    end: float
    text: str


class SubtitleDetailResponse(BaseModel):
    """The selected Subtitle for a Video, as shown in the UI and exported as files."""

    language: str
    source_type: Literal["manual", "auto"]
    text: str
    cues: list[SubtitleCueOut]
    can_analyze: bool = True


def _resolution_label(fmt: VideoFormat) -> str:
    if not fmt.has_video:
        return "仅音频"
    if fmt.height:
        return f"{fmt.height}p"
    return "视频"


def format_snapshot(fmt: VideoFormat) -> dict[str, Any]:
    return VideoFormatOut.from_port(fmt).to_snapshot()


def subtitle_snapshot(track: SubtitleTrack) -> dict[str, Any]:
    return SubtitleOut.from_port(track).model_dump()
