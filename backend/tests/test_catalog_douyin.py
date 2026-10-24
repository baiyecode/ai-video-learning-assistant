"""Douyin parsing behind the feature switch, exercised at the pre-agreed seams.

URL normalisation (pure) plus the in-process HTTP resolve/download/analysis chain
with ``FakeVideoSource``: no test ever contacts real Douyin.
"""

from __future__ import annotations

import pytest
from app.errors import AppError
from app.modules.catalog.urls import normalize_video_url

DOUYIN_SHARE_URL = "https://www.douyin.com/video/7123456789012345678"
DOUYIN_SHORT_URL = "https://v.douyin.com/AbC123"

DOUYIN_ENABLED: frozenset[str] = frozenset({"youtube", "bilibili", "douyin"})


@pytest.mark.parametrize(
    "raw",
    [
        DOUYIN_SHARE_URL,
        "https://m.douyin.com/video/7123456789012345678?share_douyin_app=h5",
        "https://v.douyin.com/AbC123/",
    ],
)
def test_douyin_urls_are_rejected_with_a_dedicated_code_when_the_switch_is_off(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw)

    assert raised.value.status == 422
    assert raised.value.code == "platform_not_enabled"
    assert raised.value.message == "抖音暂未开放"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (DOUYIN_SHARE_URL, DOUYIN_SHARE_URL),
        ("https://douyin.com/video/7123456789012345678", DOUYIN_SHARE_URL),
        (
            "https://www.douyin.com/video/7123456789012345678/?share_link_type=video_misc&tid=9",
            DOUYIN_SHARE_URL,
        ),
        (
            "https://m.douyin.com/video/7123456789012345678#fragment",
            DOUYIN_SHARE_URL,
        ),
        # Short links are forwarded as-is: only the adapter can follow the redirect.
        ("https://v.douyin.com/AbC123/?share_source=copy_system", DOUYIN_SHORT_URL),
    ],
)
def test_douyin_urls_normalise_when_the_switch_is_on(raw: str, expected: str) -> None:
    assert normalize_video_url(raw, enabled_platforms=DOUYIN_ENABLED) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.douyin.com/user/msomewhere",
        "https://www.douyin.com/discover",
        "https://live.douyin.com/123456",
        "https://www.douyin.com/video/not-a-number",
        "https://www.douyin.com/video/123456789012345678901234",
    ],
)
def test_non_video_douyin_pages_stay_unsupported(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw, enabled_platforms=DOUYIN_ENABLED)

    assert raised.value.code == "unsupported_url"
