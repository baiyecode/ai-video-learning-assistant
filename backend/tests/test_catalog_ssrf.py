"""SSRF hardening for Video URL normalisation.

Only Bilibili/YouTube video URLs are accepted; private/loopback/link-local targets,
credentials, non-http(s) schemes and non-standard ports are rejected with the stable
``unsupported_url`` code. DNS is best-effort and injected: tests never resolve names.
"""

from __future__ import annotations

import httpx
import pytest
from app.errors import AppError
from app.modules.catalog import urls
from app.modules.catalog.urls import normalize_video_url

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "raw",
    [
        "http://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "http://127.0.0.1:8000/api/videos",
        "https://localhost/watch?v=dQw4w9WgXcQ",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/watch?v=dQw4w9WgXcQ",
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "file:///etc/passwd",
        "https://user:pass@www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",
    ],
)
def test_private_and_unsupported_targets_are_rejected(raw: str) -> None:
    with pytest.raises(AppError) as raised:
        normalize_video_url(raw)

    assert raised.value.code == "unsupported_url"
    assert any("\u4e00" <= char <= "\u9fff" for char in raised.value.message)


async def test_host_resolving_to_a_private_address_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urls, "_hostname_addresses", lambda host: {"10.0.0.5"})

    with pytest.raises(AppError) as raised:
        await urls.ensure_public_url(YOUTUBE_URL)

    assert raised.value.code == "unsupported_url"


async def test_metadata_and_link_local_dns_answers_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urls, "_hostname_addresses", lambda host: {"169.254.169.254"})

    with pytest.raises(AppError) as raised:
        await urls.ensure_public_url(YOUTUBE_URL)

    assert raised.value.code == "unsupported_url"


async def test_public_dns_answers_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urls, "_hostname_addresses", lambda host: {"93.184.216.34"})

    assert normalize_video_url(YOUTUBE_URL) == YOUTUBE_URL
    await urls.ensure_public_url(YOUTUBE_URL)


async def test_dns_failure_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken(host: str) -> set[str]:
        raise OSError("dns unavailable")

    monkeypatch.setattr(urls, "_hostname_addresses", _broken)

    # Resolution failures fall through to the platform adapter; they are not SSRF evidence.
    assert normalize_video_url(YOUTUBE_URL) == YOUTUBE_URL
    await urls.ensure_public_url(YOUTUBE_URL)


def test_plain_bilibili_url_is_still_allowed() -> None:
    assert (
        normalize_video_url("https://www.bilibili.com/video/BV1xx411c7mD?t=1")
        == "https://www.bilibili.com/video/BV1xx411c7mD"
    )


async def test_resolve_endpoint_rejects_host_with_private_dns(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(urls, "_hostname_addresses", lambda host: {"10.0.0.5"})

    response = await client.post("/api/videos/resolve", json={"url": YOUTUBE_URL})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_url"
