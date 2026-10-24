"""URL identity normalisation: every accepted input collapses to one canonical URL."""

from __future__ import annotations

import pytest
from app.errors import AppError
from app.modules.catalog.urls import DEFAULT_ENABLED_PLATFORMS, normalize_video_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # YouTube: tracking params, timestamps, playlist context and fragments are dropped.
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123&index=3",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://youtu.be/dQw4w9WgXcQ?si=tracking&t=10#fragment",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/embed/dQw4w9WgXcQ?start=5",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        # Bilibili: mobile host, tracking params, timestamps, part/quality params.
        (
            "https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333.999&vd_source=abc&t=10",
            "https://www.bilibili.com/video/BV1xx411c7mD",
        ),
        (
            "https://m.bilibili.com/video/BV1xx411c7mD?p=2&broadcast_type=0",
            "https://www.bilibili.com/video/BV1xx411c7mD",
        ),
        (
            "https://www.bilibili.com/video/av170001?from=search",
            "https://www.bilibili.com/video/av170001",
        ),
        # Short links are forwarded as-is: only the adapter can follow the redirect.
        ("https://b23.tv/abcDEF", "https://b23.tv/abcDEF"),
        ("https://b23.tv/abcDEF?share_source=copy", "https://b23.tv/abcDEF"),
    ],
)
def test_accepted_urls_normalise_to_one_canonical_form(raw: str, expected: str) -> None:
    assert normalize_video_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.bilibili.com/list/watchlater?bvid=BV1xx411c7mD",
        "https://www.bilibili.com/medialist/play/ml123",
        "https://space.bilibili.com/123/favlist?fid=456",
    ],
)
def test_playlists_and_collections_are_rejected(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw)
    assert raised.value.code == "playlist_not_supported"
    assert raised.value.message


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://live.bilibili.com/12345",
        "https://www.bilibili.com/bangumi/play/ep123",
        "https://www.youtube.com/@somechannel",
        "https://example.com/video/1",
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "not a url",
        "",
    ],
)
def test_unsupported_urls_are_rejected(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw)
    assert raised.value.code == "unsupported_url"
    assert raised.value.message


# The Platform registry (``PLATFORM_HOSTS``) is the supported-list truth source the
# normalise dispatch consumes via ``_HOST_PLATFORM``. This pins the invariant that
# the two never drift: every host the registry claims must dispatch to its Platform
# branch, and no host outside the registry may ever be accepted.
@pytest.mark.parametrize(
    ("host", "path", "expected"),
    [
        ("youtube.com", "/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("www.youtube.com", "/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("m.youtube.com", "/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("youtube-nocookie.com", "/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("www.youtube-nocookie.com", "/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("youtu.be", "/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("bilibili.com", "/video/BV1xx411c7mD", "https://www.bilibili.com/video/BV1xx411c7mD"),
        ("m.bilibili.com", "/video/BV1xx411c7mD", "https://www.bilibili.com/video/BV1xx411c7mD"),
        ("b23.tv", "/abc123", "https://b23.tv/abc123"),
        ("douyin.com", "/video/7123456789012345678", "https://www.douyin.com/video/7123456789012345678"),
        ("www.douyin.com", "/video/7123456789012345678", "https://www.douyin.com/video/7123456789012345678"),
        ("m.douyin.com", "/video/7123456789012345678", "https://www.douyin.com/video/7123456789012345678"),
        ("v.douyin.com", "/abc123", "https://v.douyin.com/abc123"),
    ],
)
def test_every_registered_host_dispatches_through_the_registry(host, path, expected):
    from app.modules.catalog.urls import DOUYIN_PLATFORM, PLATFORM_HOSTS

    registered = {h for hosts in PLATFORM_HOSTS.values() for h in hosts}
    assert host in registered  # the table below mirrors the registry
    assert normalize_video_url(
        f"https://{host}{path}",
        enabled_platforms=frozenset({DOUYIN_PLATFORM}) | DEFAULT_ENABLED_PLATFORMS,
    ) == expected


def test_no_unregistered_host_is_ever_accepted():
    from app.modules.catalog.urls import PLATFORM_HOSTS

    registered = {h for hosts in PLATFORM_HOSTS.values() for h in hosts}
    for host in {"notyoutube.com", "youtu.be.evil", "b23.tv.evil", "v.douyin.com.evil"}:
        assert host not in registered
        with pytest.raises(AppError) as raised:
            normalize_video_url(f"https://{host}/watch?v=dQw4w9WgXcQ")
        assert str(raised.value.code) == "unsupported_url"
