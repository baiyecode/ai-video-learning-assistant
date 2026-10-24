"""URL identity normalisation: every accepted input collapses to one canonical URL."""

from __future__ import annotations

import pytest
from app.errors import AppError
from app.modules.catalog.urls import normalize_video_url


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
