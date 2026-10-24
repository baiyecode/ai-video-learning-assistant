"""Fake-adapter mode (``APP_FAKE_ADAPTERS=1``) exactly as the Playwright golden path sees it.

These are the seams ticket P2-09's browser run depends on: the 抖音 shape of the demo
Video, the demo-only inbox route that hands the one-time verification link to the test,
and the upgrade injection through the ordinary signed ``/billing/webhook`` contract the
demo gateway verifies with :data:`app.adapters.demo.DEMO_WEBHOOK_SECRET`. Nothing here
touches the network: the whole golden path stays in-process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from app.adapters.demo import DEMO_WEBHOOK_SECRET, DemoMediaStore, DemoVideoSource
from app.adapters.webhook_codec import sign_header
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from asgi_lifespan import LifespanManager

from tests.fakes import make_fake_adapters

_YOUTUBE_URL = "https://www.youtube.com/watch?v=demoP1Video"
_DOUYIN_URL = "https://www.douyin.com/video/7400123456789012345"
_PASSWORD = "golden-password-123"


def _demo_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Development-flavoured settings with the fake adapters switched on."""
    base: dict[str, object] = {
        "_env_file": None,
        "env": "development",
        "secret_key": "test-only-secret",
        "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'demo.db').as_posix()}",
        "data_dir": tmp_path / "data",
        "log_level": "WARNING",
        "fake_adapters": True,
        "auth_cookie_secure": False,
        "frontend_base_url": "http://127.0.0.1:5173",
        # The golden path creates Analyses back to back; the per-Account throttle would
        # reject them. The HTTP suite covers it at its own seam.
        "rate_limit_analysis_seconds": 0.0,
    }
    base.update(overrides)
    return Settings(**base)


@asynccontextmanager
async def _demo_client(
    settings: Settings, adapters: Adapters | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """Boot the real application with the real fake-adapter wiring from ``container``."""
    app = create_app(settings=settings, adapters=adapters)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post("/api/auth/register", json={"email": email, "password": _PASSWORD})
    assert response.status_code in (200, 201), response.text


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


# ------------------------------------------------------------ demo Video shapes


async def test_demo_video_source_reads_the_identity_off_the_page_address() -> None:
    source = DemoVideoSource()

    youtube = await source.resolve(_YOUTUBE_URL)
    assert (youtube.platform, youtube.platform_video_id) == ("youtube", "demoP1Video")
    assert youtube.title == "演示视频：从零理解间隔重复"
    assert len(youtube.formats) == 2

    bilibili = await source.resolve("https://www.bilibili.com/video/BV1xx411c7mD")
    assert (bilibili.platform, bilibili.platform_video_id) == ("bilibili", "BV1xx411c7mD")


async def test_demo_video_source_serves_a_douyin_shape() -> None:
    """抖音 addresses resolve as their own Platform, with one progressive mp4 (ticket #23)."""
    source = DemoVideoSource()

    long_link = await source.resolve(_DOUYIN_URL)
    assert long_link.platform == "douyin"
    assert long_link.platform_video_id == "7400123456789012345"
    assert long_link.title == "演示短视频：三分钟搞懂主动回忆"
    assert [format.ext for format in long_link.formats] == ["mp4"]
    assert long_link.webpage_url == _DOUYIN_URL

    short_link = await source.resolve("https://v.douyin.com/abcDEF/")
    assert (short_link.platform, short_link.platform_video_id) == ("douyin", "abcDEF")

    short_youtube = await source.resolve("https://youtu.be/abcDEF12345")
    assert (short_youtube.platform, short_youtube.platform_video_id) == ("youtube", "abcDEF12345")

    unknown = await source.resolve("https://www.youtube.com/watch?list=PLdemo")
    assert unknown.platform_video_id == "demoP1Video"


async def test_demo_media_store_writes_media_for_any_platform(tmp_path: Path) -> None:
    video = await DemoVideoSource().resolve(_DOUYIN_URL)
    progress: list[str] = []

    target = await DemoMediaStore().download(
        video=video,
        format_id="douyin-mp4",
        dest_dir=tmp_path / "job",
        on_progress=lambda stage, _ratio: progress.append(stage),
    )

    assert target.read_bytes() == b"demo media bytes"
    assert progress == ["downloading", "downloading", "merging"]


# ------------------------------------------------------------- demo inbox route


async def test_demo_inbox_hands_the_verification_link_to_the_browser(tmp_path: Path) -> None:
    email = "golden-path@example.com"
    async with _demo_client(_demo_settings(tmp_path)) as client:
        await _register(client, email)

        inbox = await client.get("/api/demo/inbox", params={"to": email})
        assert inbox.status_code == 200, inbox.text
        messages = inbox.json()
        assert len(messages) == 1
        assert messages[0]["subject"] == "请验证你的邮箱地址"
        assert "http://127.0.0.1:5173/verify-email?token=" in messages[0]["body"]
        token = messages[0]["verification_token"]
        assert token

        # A second address sees nothing: the inbox read is a mailbox, not a listing.
        other = await client.get("/api/demo/inbox", params={"to": "nobody@example.com"})
        assert other.json() == []

        confirmed = await client.post("/api/auth/verification/confirm", json={"token": token})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["email_verified_at"] is not None

        # The link is single-use; the mailbox keeps showing the mail it delivered.
        replay = await client.post("/api/auth/verification/confirm", json={"token": token})
        assert replay.status_code == 400
        assert len((await client.get("/api/demo/inbox")).json()) == 1


async def test_demo_inbox_is_closed_without_the_fake_adapter_switch(tmp_path: Path) -> None:
    settings = _demo_settings(tmp_path, fake_adapters=False)
    async with _demo_client(settings, make_fake_adapters()) as client:
        response = await client.get("/api/demo/inbox")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


# ------------------------------------------------------- douyin through the API


async def test_resolve_accepts_douyin_only_while_the_switch_is_open(tmp_path: Path) -> None:
    async with _demo_client(_demo_settings(tmp_path)) as closed:
        rejected = await closed.post("/api/videos/resolve", json={"url": _DOUYIN_URL})
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["code"] == "platform_not_enabled"

    async with _demo_client(_demo_settings(tmp_path, douyin_enabled=True)) as opened:
        resolved = await opened.post("/api/videos/resolve", json={"url": _DOUYIN_URL})
        assert resolved.status_code == 200, resolved.text
        body = resolved.json()
        assert body["video"]["platform"] == "douyin"
        assert body["video"]["title"] == "演示短视频：三分钟搞懂主动回忆"
        assert body["can_analyze"] is True


# ------------------------------------------------- the whole upgrade golden path


async def test_golden_path_quota_exhausted_then_upgrade_then_unlimited(tmp_path: Path) -> None:
    """Parse → free Quota exhausted → fake checkout + webhook → verified → unlimited.

    This is ticket P2-09's browser chain one layer down, so the backend half of the
    golden path stays green even while the P2-08 conversion UI is still landing.
    """
    settings = _demo_settings(tmp_path, analysis_daily_quota=1)
    email = "upgrade@example.com"
    async with _demo_client(settings) as client:
        await _register(client, email)
        token = (await client.get("/api/demo/inbox", params={"to": email})).json()[0]["verification_token"]
        assert (await client.post("/api/auth/verification/confirm", json={"token": token})).status_code == 200

        auth = await _login(client, email)
        account_id = (await client.get("/api/me", headers=auth)).json()["account"]["id"]

        assert await _resolve_and_analyse(client, auth, "goldenPath1") == "completed"

        blocked = await client.post(
            "/api/analyses",
            json={"video_id": await _video_id(client, "goldenPath2")},
            headers=auth,
        )
        assert blocked.status_code == 429, blocked.text
        assert blocked.json()["error"]["code"] == "quota_exhausted"

        checkout = await client.post("/api/billing/checkout", headers=auth)
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["url"].startswith("https://checkout.demo.invalid/")

        await _inject_payment(client, account_id)

        membership = (await client.get("/api/me/membership", headers=auth)).json()
        assert membership["status"] == "active"
        assert membership["is_vip"] is True
        assert membership["period_end"] is not None

        assert await _resolve_and_analyse(client, auth, "goldenPath3") == "completed"
        quota = (await client.get("/api/me", headers=auth)).json()["quota"]
        assert quota["daily_limit"] == -1
        assert quota["remaining"] == -1

        assert await _resolve_and_analyse(client, auth, "goldenPath4") == "completed"


async def _video_id(client: httpx.AsyncClient, platform_video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={platform_video_id}"
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return str(response.json()["video"]["id"])


async def _resolve_and_analyse(
    client: httpx.AsyncClient, auth: dict[str, str], platform_video_id: str
) -> str:
    body = {"video_id": await _video_id(client, platform_video_id)}
    created = await client.post("/api/analyses", json=body, headers=auth)
    assert created.status_code in (200, 201), created.text
    analysis_id = created.json()["id"]
    for _ in range(200):
        current = await client.get(f"/api/analyses/{analysis_id}", headers=auth)
        assert current.status_code == 200, current.text
        if current.json()["status"] in ("completed", "failed"):
            return str(current.json()["status"])
        await asyncio.sleep(0.05)
    pytest.fail("Analysis never finished")


async def _inject_payment(client: httpx.AsyncClient, account_id: str) -> None:
    """The deterministic payment-success injection: one signed webhook, unique event id."""
    created = 1_800_000_000
    payload = json.dumps(
        {
            "id": f"evt_golden_{account_id}",
            "type": "checkout.session.completed",
            "created": created,
            "data": {
                "object": {
                    "client_reference_id": account_id,
                    "customer": "cus_golden",
                    "subscription": "sub_golden",
                    "current_period_end": 1_802_592_000,
                    "metadata": {"price_id": "price_golden"},
                }
            },
        }
    ).encode()
    response = await client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sign_header(DEMO_WEBHOOK_SECRET, created, payload)},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"received": True}
