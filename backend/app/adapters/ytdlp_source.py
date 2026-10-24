"""yt-dlp backed ``VideoSource``.

The adapter shells out to the ``yt-dlp`` executable (never imports its Python API from
business modules) and translates the JSON metadata into the port's dataclasses.
All failure modes are mapped to stable ``AppError`` codes or ``VideoUnavailableError``.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app import messages
from app.config import Settings
from app.errors import AppError, ErrorCode
from app.ports import ResolvedVideo, SubtitlePayload, SubtitleTrack, VideoFormat, VideoUnavailableError

logger = logging.getLogger("app.adapters.ytdlp")

_EXTRACT_TIMEOUT_SECONDS = 60.0
_SUBTITLE_TIMEOUT_SECONDS = 90.0
_MAX_LABEL_NOTE = 40
_NON_SUBTITLE_LANGUAGES = {"live_chat", "danmaku"}

_MESSAGE_MEMBERS_HINT = "会员专属"
_MESSAGE_SERVICE_UNAVAILABLE = "解析服务暂时不可用，请稍后再试"
_MESSAGE_TIMEOUT = "解析超时，请稍后重试"
_MESSAGE_SUBTITLE_FAILED = "字幕获取失败，请稍后重试"

_HTML_TAG = re.compile(r"<[^>]+>")
_TIMESTAMP_LINE = re.compile(r"^\s*(\S+)\s*-->\s*(\S+)")


class YtDlpVideoSource:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def resolve(self, url: str) -> ResolvedVideo:
        info = await self._extract_info(url)

        if info.get("_type") == "playlist":
            raise AppError(422, ErrorCode.PLAYLIST_NOT_SUPPORTED, messages.PLAYLIST_NOT_SUPPORTED)
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise AppError(422, ErrorCode.UNSUPPORTED_URL, "暂不支持直播链接，请提供已发布的单个视频")

        availability = str(info.get("availability") or "")
        if availability in {"private", "needs_auth", "login_required"}:
            raise VideoUnavailableError(availability)
        members_only = availability in {"premium_only", "subscriber_only"}
        is_drm = _has_drm(info)

        platform = _platform_of(info)
        video_id = str(info.get("id") or "").strip()
        if not video_id:
            raise AppError(502, ErrorCode.RESOLVE_FAILED, messages.RESOLVE_FAILED)

        duration = _int_or_none(info.get("duration")) or 0
        webpage_url = str(info.get("webpage_url") or url)
        thumbnail = info.get("thumbnail")
        if isinstance(thumbnail, list):
            thumbnail = next((item for item in thumbnail if isinstance(item, str)), None)

        return ResolvedVideo(
            platform=platform,
            platform_video_id=video_id,
            title=str(info.get("title") or video_id),
            duration_seconds=max(0, duration),
            webpage_url=webpage_url,
            uploader=_first_str(info.get("uploader"), info.get("channel")),
            thumbnail_url=thumbnail if isinstance(thumbnail, str) else None,
            formats=_formats_of(info),
            subtitles=_subtitle_tracks(info),
            is_drm=is_drm,
            is_members_only=members_only,
        )

    async def fetch_subtitle(self, video: ResolvedVideo, track: SubtitleTrack) -> SubtitlePayload:
        executable = shutil.which("yt-dlp")
        if executable is None:
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_SERVICE_UNAVAILABLE)

        with tempfile.TemporaryDirectory(prefix="subtitle-") as tmp_dir:
            args = [
                executable,
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                "--no-progress",
                "--write-auto-subs" if track.is_automatic else "--write-subs",
                "--sub-langs",
                track.language,
                "--sub-format",
                "json3/vtt/srt/best",
                "--socket-timeout",
                "15",
                "-o",
                str(Path(tmp_dir) / "subtitle.%(ext)s"),
                video.webpage_url,
            ]
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=_SUBTITLE_TIMEOUT_SECONDS
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise AppError(504, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_TIMEOUT) from exc

            if process.returncode != 0:
                logger.warning(
                    "ytdlp_subtitle_failed",
                    extra={
                        "event": "ytdlp_subtitle_failed",
                        "language": track.language,
                        "stderr": stderr.decode("utf-8", errors="replace")[-500:],
                    },
                )
                # ``subtitles_unavailable`` always means HTTP 409, never 502.
                raise AppError(409, ErrorCode.SUBTITLES_UNAVAILABLE, _MESSAGE_SUBTITLE_FAILED)

            cues = await _read_first_subtitle(Path(tmp_dir))

        if not cues:
            raise AppError(409, ErrorCode.SUBTITLES_UNAVAILABLE, _MESSAGE_SUBTITLE_FAILED)
        return SubtitlePayload(
            track=track,
            cues=cues,
            text="\n".join(text for _, _, text in cues),
        )

    async def _extract_info(self, url: str) -> dict[str, Any]:
        executable = shutil.which("yt-dlp")
        if executable is None:
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_SERVICE_UNAVAILABLE)

        args = [
            executable,
            "--dump-single-json",
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "--socket-timeout",
            "15",
            url,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            logger.warning("ytdlp_spawn_failed", extra={"event": "ytdlp_spawn_failed"})
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_SERVICE_UNAVAILABLE) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_EXTRACT_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AppError(504, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_TIMEOUT) from exc

        if process.returncode != 0:
            _raise_for_stderr(stderr.decode("utf-8", errors="replace"))

        try:
            payload = json.loads(stdout.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("ytdlp_bad_json", extra={"event": "ytdlp_bad_json"})
            raise AppError(502, ErrorCode.RESOLVE_FAILED, messages.RESOLVE_FAILED) from exc

        if not isinstance(payload, dict):
            raise AppError(502, ErrorCode.RESOLVE_FAILED, messages.RESOLVE_FAILED)
        return payload


def _raise_for_stderr(stderr: str) -> None:
    lowered = stderr.lower()
    logger.warning(
        "ytdlp_extract_failed",
        extra={"event": "ytdlp_extract_failed", "stderr": stderr[-500:]},
    )
    if "playlist" in lowered:
        raise AppError(422, ErrorCode.PLAYLIST_NOT_SUPPORTED, messages.PLAYLIST_NOT_SUPPORTED)
    if "drm" in lowered:
        raise AppError(403, ErrorCode.DRM_PROTECTED, messages.DRM_PROTECTED)
    if _MESSAGE_MEMBERS_HINT in stderr or "members-only" in lowered or "premium" in lowered:
        raise AppError(403, ErrorCode.MEMBERS_ONLY, messages.MEMBERS_ONLY)
    if any(
        marker in lowered
        for marker in ("unavailable", "private", "removed", "deleted", "not available", "404")
    ):
        raise VideoUnavailableError(stderr[-200:])
    raise AppError(502, ErrorCode.RESOLVE_FAILED, messages.RESOLVE_FAILED)


def _platform_of(info: dict[str, Any]) -> str:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    if "bilibili" in extractor:
        return "bilibili"
    if "youtube" in extractor:
        return "youtube"
    raise AppError(422, ErrorCode.UNSUPPORTED_URL, messages.UNSUPPORTED_PLATFORM)


def _has_drm(info: dict[str, Any]) -> bool:
    if info.get("_has_drm") or info.get("has_drm"):
        return True
    for raw in info.get("formats") or []:
        if isinstance(raw, dict) and raw.get("has_drm"):
            return True
    return False


def _formats_of(info: dict[str, Any]) -> tuple[VideoFormat, ...]:
    formats: list[VideoFormat] = []
    for raw in info.get("formats") or []:
        if not isinstance(raw, dict) or raw.get("has_drm"):
            continue
        vcodec = raw.get("vcodec")
        acodec = raw.get("acodec")
        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")
        if not has_video and not has_audio:
            continue
        format_id = str(raw.get("format_id") or "").strip()
        if not format_id:
            continue
        formats.append(
            VideoFormat(
                format_id=format_id,
                label=_format_label(raw, has_video=has_video, has_audio=has_audio),
                ext=str(raw.get("ext") or "mp4"),
                width=_int_or_none(raw.get("width")),
                height=_int_or_none(raw.get("height")),
                filesize=_int_or_none(raw.get("filesize") or raw.get("filesize_approx")),
                has_video=has_video,
                has_audio=has_audio,
            )
        )
    return tuple(formats)


def _format_label(raw: dict[str, Any], *, has_video: bool, has_audio: bool) -> str:
    height = _int_or_none(raw.get("height"))
    note = str(raw.get("format_note") or "").strip()[:_MAX_LABEL_NOTE]
    if not has_video:
        return f"仅音频 · {note}" if note else "仅音频"
    base = f"{height}p" if height else "视频"
    if note and note.lower() not in base.lower():
        return f"{base} · {note}"
    return base


def _subtitle_tracks(info: dict[str, Any]) -> tuple[SubtitleTrack, ...]:
    tracks: list[SubtitleTrack] = []
    seen: set[str] = set()

    for language, entries in (info.get("subtitles") or {}).items():
        if language in _NON_SUBTITLE_LANGUAGES or not language:
            continue
        tracks.append(SubtitleTrack(language=language, name=_subtitle_name(entries, language)))
        seen.add(language)

    for language, entries in (info.get("automatic_captions") or {}).items():
        if language in seen or language in _NON_SUBTITLE_LANGUAGES or not language:
            continue
        tracks.append(
            SubtitleTrack(
                language=language,
                name=_subtitle_name(entries, language),
                is_automatic=True,
            )
        )
    return tuple(tracks)


def _subtitle_name(entries: Any, language: str) -> str:
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name"):
                return str(entry["name"])
    return language


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _read_first_subtitle(directory: Path) -> list[tuple[float, float, str]]:
    """yt-dlp writes one file per requested language; take the first parseable one."""
    return await asyncio.to_thread(_read_first_subtitle_sync, directory)


def _read_first_subtitle_sync(directory: Path) -> list[tuple[float, float, str]]:
    known = {".json3", ".json", ".vtt", ".srt"}
    candidates = sorted(
        (path for path in directory.iterdir() if path.is_file()),
        key=lambda path: (path.suffix.lower() not in known, path.name),
    )
    for path in candidates:
        cues = _parse_subtitle_file(path)
        if cues:
            return cues
    return []


def _parse_subtitle_file(path: Path) -> list[tuple[float, float, str]]:
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    suffix = path.suffix.lower()
    if suffix in {".json3", ".json"}:
        return _parse_json_subtitle(raw)
    if suffix in {".vtt", ".srt"}:
        return _parse_timed_blocks(raw)
    return []


def _parse_json_subtitle(raw: str) -> list[tuple[float, float, str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    events = data.get("events")
    if isinstance(events, list):
        return _parse_youtube_events(events)
    body = data.get("body")
    if isinstance(body, list):
        return _parse_bilibili_body(body)
    return []


def _parse_youtube_events(events: list[Any]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segments = event.get("segs")
        if not isinstance(segments, list):
            continue
        text = " ".join(
            str(segment.get("utf8") or "")
            for segment in segments
            if isinstance(segment, dict)
        ).strip()
        start_ms = _float_or_none(event.get("tStartMs"))
        duration_ms = _float_or_none(event.get("dDurationMs")) or 0.0
        if not text or start_ms is None:
            continue
        start = start_ms / 1000
        end = max(start + 0.001, (start_ms + duration_ms) / 1000)
        cues.append((start, end, _clean_cue_text(text)))
    return cues


def _parse_bilibili_body(body: list[Any]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        start = _float_or_none(item.get("from"))
        end = _float_or_none(item.get("to"))
        text = _clean_cue_text(str(item.get("content") or ""))
        if start is None or end is None or not text:
            continue
        cues.append((start, max(start, end), text))
    return cues


def _parse_timed_blocks(raw: str) -> list[tuple[float, float, str]]:
    """Parse both WebVTT and SRT: blocks of ``[index] timing text...``."""
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\r?\n\s*\r?\n", raw.strip()):
        lines = block.splitlines()
        for index, line in enumerate(lines):
            match = _TIMESTAMP_LINE.match(line)
            if match is None:
                continue
            start = _parse_timestamp(match.group(1))
            end = _parse_timestamp(match.group(2))
            if start is None or end is None:
                break
            text = " ".join(_clean_cue_text(part) for part in lines[index + 1 :]).strip()
            if text:
                cues.append((start, max(start, end), text))
            break
    return cues


def _parse_timestamp(value: str) -> float | None:
    pieces = value.strip().replace(",", ".").split(":")
    try:
        if len(pieces) == 3:
            hours, minutes, seconds = pieces
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(pieces) == 2:
            minutes, seconds = pieces
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def _clean_cue_text(value: str) -> str:
    return html.unescape(_HTML_TAG.sub("", value)).strip()


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
