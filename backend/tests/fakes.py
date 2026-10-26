"""Deterministic ports for tests. Extend these, never fork them."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.adapters.webhook_codec import sign_header, verify_and_decode
from app.container import Adapters
from app.ports import (
    CheckoutSession,
    CustomerPortal,
    OutboundEmail,
    ResolvedVideo,
    SubtitlePayload,
    SubtitleTrack,
    VideoFormat,
    WebhookEvent,
)
from app.timeutil import shanghai_day

FAKE_CHECKOUT_URL = "https://checkout.stripe.test/c/fake-checkout"
FAKE_PORTAL_URL = "https://portal.stripe.test/b/fake-portal"
FAKE_WEBHOOK_SECRET = "whsec_fake"
#: Fixed signature timestamp for emitted webhook headers; the fake codec has no
#: replay window, so deterministic bytes keep test payloads stable.
FAKE_WEBHOOK_TIMESTAMP = 1_768_471_200


def sign_webhook(body: bytes, *, secret: str = FAKE_WEBHOOK_SECRET) -> str:
    """A valid ``Stripe-Signature`` header for a fake-gateway webhook body."""
    return sign_header(secret, FAKE_WEBHOOK_TIMESTAMP, body)


def webhook_event_body(
    event_id: str,
    event_type: str,
    created: datetime,
    object_payload: dict[str, object] | None = None,
) -> bytes:
    """A Stripe-style webhook envelope the fake gateway can verify and decode."""
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "created": int(created.timestamp()),
            "data": {"object": object_payload or {}},
        },
        sort_keys=True,
    ).encode()


def checkout_completed_body(
    event_id: str,
    account_id: str,
    *,
    created: datetime,
    period_end: datetime | None = None,
    subscription_id: str = "sub_fake_1",
    customer_id: str = "cus_fake_1",
    price_id: str = "price_fake_monthly",
) -> bytes:
    """The wire shape behind ``checkout.session.completed``: a Checkout Session object."""
    session_object: dict[str, object] = {
        "client_reference_id": account_id,
        "subscription": subscription_id,
        "customer": customer_id,
        "metadata": {"account_id": account_id, "price_id": price_id},
    }
    if period_end is not None:
        session_object["current_period_end"] = int(period_end.timestamp())
    return webhook_event_body(event_id, "checkout.session.completed", created, session_object)


def lifecycle_event_body(
    event_id: str,
    event_type: str,
    created: datetime,
    *,
    account_id: str | None = None,
    subscription_id: str = "sub_fake_1",
    customer_id: str = "cus_fake_1",
    period_end: datetime | None = None,
    subscription_status: str | None = None,
    cancel_at_period_end: bool | None = None,
) -> bytes:
    """The wire shape of an invoice/subscription lifecycle event (Stripe-style object).

    ``account_id`` is optional on purpose: real invoice and subscription events name
    only Stripe ids, and the state machine must still find the local subscription.
    """
    obj: dict[str, object] = {"subscription": subscription_id, "customer": customer_id}
    if account_id is not None:
        obj["metadata"] = {"account_id": account_id}
    if period_end is not None:
        obj["current_period_end"] = int(period_end.timestamp())
    if subscription_status is not None:
        obj["status"] = subscription_status
    if cancel_at_period_end is not None:
        obj["cancel_at_period_end"] = cancel_at_period_end
    return webhook_event_body(event_id, event_type, created, obj)

#: The one Douyin Video the fake short-link wrapper unwraps to.
DOUYIN_DEFAULT_VIDEO_ID = "7123456789012345678"
_DOUYIN_SHARE_URL = re.compile(r"^https://www\.douyin\.com/video/(\d{5,23})$")
_DOUYIN_SHORT_URL = re.compile(r"^https://v\.douyin\.com/[A-Za-z0-9_-]+$")


def sample_subtitle_track(language: str = "zh-Hans", *, automatic: bool = False) -> SubtitleTrack:
    return SubtitleTrack(language=language, name="中文（简体）", is_automatic=automatic)


def sample_video(
    *,
    platform: str = "youtube",
    platform_video_id: str = "dQw4w9WgXcQ",
    title: str = "示例视频",
    duration_seconds: int = 300,
    is_drm: bool = False,
    is_members_only: bool = False,
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
        is_drm=is_drm,
        is_members_only=is_members_only,
    )


def sample_douyin_video(
    *,
    platform_video_id: str = DOUYIN_DEFAULT_VIDEO_ID,
    title: str = "抖音示例视频",
    duration_seconds: int = 15,
    with_subtitle: bool = False,
) -> ResolvedVideo:
    """Douyin shape: cover + duration, one server-side watermarked format, no captions."""
    return ResolvedVideo(
        platform="douyin",
        platform_video_id=platform_video_id,
        title=title,
        duration_seconds=duration_seconds,
        webpage_url=f"https://www.douyin.com/video/{platform_video_id}",
        uploader="抖音作者",
        thumbnail_url="https://p3-douyin.example/cover.jpg",
        formats=(
            VideoFormat(
                format_id="watermark_mp4",
                label="带水印",
                ext="mp4",
                width=720,
                height=1280,
                filesize=8_000_000,
            ),
        ),
        subtitles=(sample_subtitle_track(),) if with_subtitle else (),
    )


@dataclass
class FrozenClock:
    """A Clock frozen at an instant; advance it explicitly in tests."""

    instant: datetime = field(default_factory=lambda: datetime(2026, 1, 15, 8, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.instant

    def today(self) -> date:
        return shanghai_day(self.instant)

    def advance(self, *, seconds: float = 0, days: int = 0) -> datetime:
        self.instant = self.instant + timedelta(seconds=seconds, days=days)
        return self.instant


@dataclass
class FakeVideoSource:
    """Resolves URLs from an in-memory catalogue and serves canned subtitles.

    Unregistered Douyin URLs are recognised by shape: a ``www.douyin.com/video/<id>``
    page resolves to that id, and a ``v.douyin.com/<code>`` short link unwraps to the
    default Douyin Video — mirroring the production adapter following the redirect.
    """

    videos: dict[str, ResolvedVideo] = field(default_factory=dict)
    subtitles: dict[tuple[str, str], SubtitlePayload] = field(default_factory=dict)
    resolve_error: Exception | None = None
    resolve_calls: list[str] = field(default_factory=list)
    subtitle_calls: list[tuple[str, str]] = field(default_factory=list)

    # Deterministic concurrency controls for ``fetch_subtitle`` (see the module docstring
    # rule "extend, never fork"). Every call waits on ``subtitle_barrier`` before
    # returning, so a test can hold two concurrent resolves past their "no Subtitle yet"
    # read. ``subtitle_entered`` is set as soon as a call starts; ``subtitle_fail_on_call``
    # picks the 1-based call that raises, waiting for ``subtitle_fail_gate`` first so the
    # other request can commit the winning row.
    subtitle_barrier: asyncio.Barrier | None = None
    subtitle_entered: asyncio.Event | None = None
    subtitle_fail_on_call: int | None = None
    subtitle_fail_gate: asyncio.Event | None = None
    subtitle_error: Exception | None = None

    async def resolve(self, url: str) -> ResolvedVideo:
        self.resolve_calls.append(url)
        if self.resolve_error is not None:
            raise self.resolve_error
        if url in self.videos:
            return self.videos[url]
        share = _DOUYIN_SHARE_URL.fullmatch(url)
        if share is not None:
            return sample_douyin_video(platform_video_id=share.group(1))
        if _DOUYIN_SHORT_URL.fullmatch(url):
            return sample_douyin_video()
        return sample_video()

    async def fetch_subtitle(self, video: ResolvedVideo, track: SubtitleTrack) -> SubtitlePayload:
        self.subtitle_calls.append((video.platform_video_id, track.language))
        call_number = len(self.subtitle_calls)
        if self.subtitle_entered is not None:
            self.subtitle_entered.set()
        if self.subtitle_barrier is not None:
            await self.subtitle_barrier.wait()
        if self.subtitle_fail_on_call == call_number:
            if self.subtitle_fail_gate is not None:
                await self.subtitle_fail_gate.wait()
            raise self.subtitle_error or RuntimeError("synthetic subtitle fetch failure")
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
    """Streams scripted chunks; scripts errors, partial failures, delays and hangs.

    - ``error``: raised before the first chunk (or after ``error_after`` chunks).
    - ``error_after``: emit this many chunks, then raise ``error``.
    - ``delay_seconds``: sleep between chunks (keeps an Analysis in progress).
    - ``hang_seconds``: sleep before yielding anything (exercises the timeout).
    - ``responder``: derive the response from the prompt (map-reduce echo tests);
      when set it replaces ``chunks``.
    """

    chunks: list[str] = field(default_factory=lambda: ["这是", "一段", "摘要"])
    error: Exception | None = None
    error_after: int | None = None
    delay_seconds: float = 0.0
    hang_seconds: float | None = None
    responder: Callable[[str], str] | None = None
    prompts: list[str] = field(default_factory=list)

    def stream(self, *, prompt: str) -> AsyncIterator[str]:
        self.prompts.append(prompt)

        async def _generate() -> AsyncIterator[str]:
            if self.hang_seconds is not None:
                await asyncio.sleep(self.hang_seconds)
            if self.error is not None and self.error_after is None:
                raise self.error
            if self.responder is not None:
                text = self.responder(prompt)
                if text:
                    yield text
                return
            for index, chunk in enumerate(self.chunks):
                if self.error_after is not None and index >= self.error_after:
                    raise self.error or RuntimeError("synthetic summarizer failure")
                if self.delay_seconds:
                    await asyncio.sleep(self.delay_seconds)
                yield chunk

        return _generate()


@dataclass
class FakeBudgetLedger:
    """In-memory daily USD ledger; ``recorded`` shows every billed Summarizer call."""

    budget_usd: float = 10.0
    spent_usd: float = 0.0
    recorded: list[float] = field(default_factory=list)
    can_spend_calls: list[float] = field(default_factory=list)

    async def can_spend(self, estimated_usd: float) -> bool:
        self.can_spend_calls.append(estimated_usd)
        return self.spent_usd + estimated_usd <= self.budget_usd

    async def record(self, usd: float) -> None:
        self.spent_usd += usd
        self.recorded.append(usd)


@dataclass
class FakeEmailSender:
    """In-memory inbox for the EmailSender port; never touches a real mail service.

    - ``sent``: every delivered message, so tests can read verification links back out.
    - ``fail_with``: raise this instead of delivering (scripted delivery failure).
    """

    sent: list[OutboundEmail] = field(default_factory=list)
    fail_with: Exception | None = None

    async def send(self, message: OutboundEmail) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(message)

    def messages_for(self, to: str | None = None) -> list[OutboundEmail]:
        """ObservableInbox view, newest-first, optionally narrowed to one address."""
        messages = [message for message in self.sent if to is None or message.to == to]
        return list(reversed(messages))


@dataclass
class FakeBillingGateway:
    """In-memory Stripe stand-in; programmable failures, zero network.

    - ``fail_with``: raised by every checkout call (e.g. an ``AppError`` for an unavailable gateway).
    - ``created_checkouts``: every checkout call, for wiring assertions.
    - ``webhook_secret`` / ``webhook_fail_with``: webhook verification follows the real
      Stripe signature scheme via the shared codec; ``webhook_fail_with`` makes the
      gateway raise before decoding (provider-outage tests).
    - ``portal_url`` / ``created_portals`` / ``portal_fail_with``: the customer-portal
      mint (P2-04 self-service entry), programmable like checkout.
    """

    fail_with: Exception | None = None
    checkout_url: str = FAKE_CHECKOUT_URL
    created_checkouts: list[dict[str, object]] = field(default_factory=list)
    webhook_secret: str = FAKE_WEBHOOK_SECRET
    webhook_fail_with: Exception | None = None
    portal_url: str = FAKE_PORTAL_URL
    created_portals: list[dict[str, object]] = field(default_factory=list)
    portal_fail_with: Exception | None = None

    async def create_checkout(
        self,
        *,
        account_id: str,
        email: str | None,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        if self.fail_with is not None:
            raise self.fail_with
        self.created_checkouts.append(
            {
                "account_id": account_id,
                "email": email,
                "price_id": price_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return CheckoutSession(id=f"cs_fake_{len(self.created_checkouts)}", url=self.checkout_url)

    async def create_portal(
        self,
        *,
        provider_customer_id: str,
        return_url: str,
    ) -> CustomerPortal:
        if self.portal_fail_with is not None:
            raise self.portal_fail_with
        self.created_portals.append(
            {"provider_customer_id": provider_customer_id, "return_url": return_url}
        )
        return CustomerPortal(url=self.portal_url)

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        if self.webhook_fail_with is not None:
            raise self.webhook_fail_with
        return verify_and_decode(payload=payload, signature_header=signature, secret=self.webhook_secret)


def make_fake_adapters(
    *,
    video_source: FakeVideoSource | None = None,
    media_store: FakeMediaStore | None = None,
    summarizer: FakeSummarizer | None = None,
    clock: FrozenClock | None = None,
    budget_ledger: FakeBudgetLedger | None = None,
    billing_gateway: FakeBillingGateway | None = None,
    email_sender: FakeEmailSender | None = None,
) -> Adapters:
    """Build the full Adapters container with fakes. Pass overrides by keyword."""
    return Adapters(
        video_source=video_source or FakeVideoSource(),
        media_store=media_store or FakeMediaStore(),
        summarizer=summarizer or FakeSummarizer(),
        clock=clock or FrozenClock(),
        budget_ledger=budget_ledger or FakeBudgetLedger(),
        billing_gateway=billing_gateway or FakeBillingGateway(),
        email_sender=email_sender or FakeEmailSender(),
    )
