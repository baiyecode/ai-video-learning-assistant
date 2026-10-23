"""Video URL identity normalisation.

A URL is only an input: the Video's identity is ``(Platform, Platform video id)``.
This module strips everything that must not influence identity — tracking params,
timestamps, fragments, quality/part params, mobile hosts, short-link wrappers —
and rejects inputs that are not a single Bilibili/YouTube video.

Short links (``b23.tv``) cannot be mapped to a Platform video id offline, so they are
forwarded to the ``VideoSource`` adapter, which follows the redirect. Identity still
comes from the adapter's ``ResolvedVideo``, so two wrappers of one Video deduplicate.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlsplit

from app.errors import AppError, ErrorCode

_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_BILIBILI_BVID = re.compile(r"BV[0-9A-Za-z]{10}")
_BILIBILI_AVID = re.compile(r"av\d+", re.IGNORECASE)
_SHORT_LINK_CODE = re.compile(r"[A-Za-z0-9_-]+")

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_BILIBILI_VIDEO_HOSTS = {"bilibili.com", "m.bilibili.com"}
_BILIBILI_SHORT_HOSTS = {"b23.tv"}

_MESSAGE_UNSUPPORTED = "暂不支持该链接，请提供 B 站或 YouTube 的单个视频链接"
_MESSAGE_PLAYLIST = "暂不支持播放列表、合集或收藏夹，请提供单个视频链接"
_MESSAGE_LIVE = "暂不支持直播链接，请提供已发布的单个视频"


def normalize_video_url(raw: str) -> str:
    """Return the canonical single-video URL or raise :class:`AppError`.

    Canonical forms:
    - ``https://www.youtube.com/watch?v=<id>``
    - ``https://www.bilibili.com/video/<BV...|av...>``
    - ``https://b23.tv/<code>`` (short link, resolved by the adapter)

    Bilibili multi-part parameters (``p=``) are part of the same Platform video and are
    dropped: P1 treats one BV/av id as one Video.

    This is a pure, synchronous structural check: only http(s) URLs on the
    Bilibili/YouTube hosts are accepted, with no credentials and a standard port, and
    IP literals / private name suffixes are rejected outright. DNS is checked
    separately by :func:`ensure_public_url` so the async request path never blocks.
    """
    text = (raw or "").strip()
    if not text:
        raise _unsupported()

    parsed = urlsplit(text)
    if not parsed.scheme:
        # Be forgiving about pasted bare links, e.g. "youtu.be/abc".
        parsed = urlsplit(f"https://{text}")

    if parsed.scheme.lower() not in {"http", "https"}:
        raise _unsupported()
    if parsed.username or parsed.password:
        raise _unsupported()
    try:
        port = parsed.port
    except ValueError:
        raise _unsupported() from None
    if port not in (None, 80, 443):
        raise _unsupported()

    host = (parsed.hostname or "").lower()
    if not host:
        raise _unsupported()
    _reject_private_host(host)

    if host in _YOUTUBE_HOSTS or host == "youtu.be":
        return _normalise_youtube(host, parsed.path, parsed.query)
    if host in _BILIBILI_SHORT_HOSTS:
        return _normalise_bilibili_short(parsed.path)
    if host in _BILIBILI_VIDEO_HOSTS or host.endswith(".bilibili.com"):
        return _normalise_bilibili(host, parsed.path, parsed.query)
    raise _unsupported()


async def ensure_public_url(url: str) -> None:
    """Resolve an already-normalised URL off the event loop and reject private answers.

    DNS is best-effort: resolution failures fall through to the platform adapter, which
    will fail later if the host is unusable. The lookup runs in a worker thread so a
    slow resolver cannot stall every other request in the process.
    """
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        raise _unsupported()
    try:
        addresses = await asyncio.to_thread(_hostname_addresses, host)
    except (OSError, UnicodeError):
        return
    if any(_is_blocked_address(address) for address in addresses):
        raise _unsupported()


def _hostname_addresses(host: str) -> set[str]:
    """Resolve ``host`` to IP address strings.

    Best-effort: callers treat resolution failures as "no evidence of SSRF". Tests
    monkeypatch this function (or pass ``resolver=``) so they never touch DNS.
    """
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return {str(info[4][0]) for info in infos}


def _reject_private_host(host: str) -> None:
    """Reject localhost-style names and IP literals before any resolution."""
    if (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".home.arpa")
    ):
        raise _unsupported()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    raise _unsupported()


def _is_blocked_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(str(address).strip("[]").split("%")[0])
    except ValueError:
        return True
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def _normalise_youtube(host: str, path: str, query: str) -> str:
    if host == "youtu.be":
        video_id = path.strip("/")
        if not _YOUTUBE_ID.fullmatch(video_id) or "/" in path.strip("/"):
            raise _unsupported()
        return _youtube_watch_url(video_id)

    clean_path = path.rstrip("/") or "/"
    if clean_path in {"/playlist", "/playlist/"}:
        raise _playlist()
    if clean_path.startswith("/live/"):
        raise AppError(422, ErrorCode.UNSUPPORTED_URL, _MESSAGE_LIVE)
    if clean_path.startswith("/@"):
        raise _unsupported()

    if clean_path.startswith("/watch") or clean_path == "/watch":
        params = parse_qs(query)
        video_ids = params.get("v") or []
        video_id = video_ids[0].strip() if video_ids else ""
        if not video_id:
            if params.get("list"):
                raise _playlist()
            raise _unsupported()
        if not _YOUTUBE_ID.fullmatch(video_id):
            raise _unsupported()
        return _youtube_watch_url(video_id)

    for prefix in ("/shorts/", "/embed/", "/v/"):
        if clean_path.startswith(prefix):
            video_id = clean_path[len(prefix) :].split("/")[0]
            if not _YOUTUBE_ID.fullmatch(video_id):
                raise _unsupported()
            return _youtube_watch_url(video_id)

    raise _unsupported()


def _normalise_bilibili_short(path: str) -> str:
    code = path.strip("/")
    if not code or "/" in code or not _SHORT_LINK_CODE.fullmatch(code):
        raise _unsupported()
    return f"https://b23.tv/{code}"


def _normalise_bilibili(host: str, path: str, query: str) -> str:
    clean_path = path.rstrip("/") or "/"

    if host == "live.bilibili.com" or clean_path.startswith("/live/"):
        raise AppError(422, ErrorCode.UNSUPPORTED_URL, _MESSAGE_LIVE)
    if clean_path.startswith(("/bangumi/", "/read/", "/opus/", "/festival/")):
        raise _unsupported()
    if host == "space.bilibili.com":
        if any(marker in clean_path for marker in ("/favlist", "/collectiondetail", "/channel/")):
            raise _playlist()
        raise _unsupported()
    if clean_path.startswith(("/list/", "/medialist/", "/channel/collectiondetail")):
        raise _playlist()

    if clean_path.startswith("/video/"):
        parts = clean_path[len("/video/") :].split("/")
        video_ref = parts[0] if parts else ""
        if not video_ref:
            raise _unsupported()
        if _BILIBILI_BVID.fullmatch(video_ref):
            return f"https://www.bilibili.com/video/{video_ref}"
        if _BILIBILI_AVID.fullmatch(video_ref):
            return f"https://www.bilibili.com/video/{video_ref.lower()}"
        raise _unsupported()

    raise _unsupported()


def _youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _unsupported() -> AppError:
    return AppError(422, ErrorCode.UNSUPPORTED_URL, _MESSAGE_UNSUPPORTED)


def _playlist() -> AppError:
    return AppError(422, ErrorCode.PLAYLIST_NOT_SUPPORTED, _MESSAGE_PLAYLIST)
