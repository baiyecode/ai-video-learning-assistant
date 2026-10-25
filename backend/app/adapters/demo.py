"""Deterministic offline adapters for the Playwright golden path.

Enabled only by ``APP_FAKE_ADAPTERS=1`` (and rejected in production). They never touch
the network, yt-dlp or DeepSeek, so the end-to-end test exercises the real HTTP, SSE,
database and download paths with stable content.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.adapters.webhook_codec import verify_and_decode
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

DEMO_WEBHOOK_SECRET = "whsec_demo"

_DEMO_ID = "demoP1Video"
_DEMO_DOUYIN_ID = "demoDouyinVideo"
_DEMO_TITLE = "演示视频：从零理解间隔重复"
_DEMO_DOUYIN_TITLE = "演示短视频：三分钟搞懂主动回忆"
_DEMO_SUBTITLE = (
    "间隔重复是一种利用遗忘曲线安排复习的学习方法。"
    "第一次复习安排在一天后，第二次三天后，随后逐渐拉长间隔。"
    "每次复习时先主动回忆，再核对答案，效果远好于被动重读。"
    "把知识拆成小卡片，并只保留一个明确问题，可以减少记忆负担。"
    "坚持记录复习结果，让算法根据掌握程度调整下一次出现的时间。"
)


class DemoVideoSource:
    """Resolves any supported URL to canned, deterministic content.

    Platform and Platform video id are read off the (already normalised) page address
    rather than hard-coded, for two reasons the golden path depends on: one Account can
    burn several Quota units on distinct Videos (ticket P2-09), and a 抖音 address gets
    its own shape (ticket #23 leftover) so the user-visible platform label and the
    export filename differ from YouTube's. All other content stays canned.
    """

    async def resolve(self, url: str) -> ResolvedVideo:
        platform, platform_video_id = _demo_identity(url)
        is_douyin = platform == "douyin"
        return ResolvedVideo(
            platform=platform,
            platform_video_id=platform_video_id,
            title=_DEMO_DOUYIN_TITLE if is_douyin else _DEMO_TITLE,
            duration_seconds=180 if is_douyin else 300,
            webpage_url=url,
            uploader="演示作者",
            thumbnail_url=None,
            formats=_DEMO_DOUYIN_FORMATS if is_douyin else _DEMO_FORMATS,
            subtitles=(SubtitleTrack(language="zh-Hans", name="中文（简体）"),),
        )

    async def fetch_subtitle(self, video: ResolvedVideo, track: SubtitleTrack) -> SubtitlePayload:
        return SubtitlePayload(
            track=track,
            cues=[
                (0.0, 3.0, "间隔重复是一种利用遗忘曲线安排复习的学习方法。"),
                (3.0, 6.0, "第一次复习安排在一天后，第二次三天后，随后逐渐拉长间隔。"),
                (6.0, 9.0, "每次复习时先主动回忆，再核对答案，效果远好于被动重读。"),
                (9.0, 12.0, "把知识拆成小卡片，并只保留一个明确问题，可以减少记忆负担。"),
                (12.0, 15.0, "坚持记录复习结果，让算法根据掌握程度调整下一次出现的时间。"),
            ],
            text=_DEMO_SUBTITLE,
        )


_DEMO_FORMATS = (
    VideoFormat(
        format_id="best",
        label="最佳画质",
        ext="mp4",
        height=720,
        filesize=1024,
    ),
    VideoFormat(
        format_id="bestaudio",
        label="仅音频",
        ext="m4a",
        filesize=512,
        has_video=False,
    ),
)

#: 抖音 ships one progressive mp4, exactly like the yt-dlp adapter's douyin branch.
_DEMO_DOUYIN_FORMATS = (
    VideoFormat(
        format_id="douyin-mp4",
        label="高清",
        ext="mp4",
        height=720,
        filesize=2048,
    ),
)


def _demo_identity(url: str) -> tuple[str, str]:
    """The canned Video's ``(platform, platform_video_id)`` for a normalised page address.

    Only the identity varies per address; every other field is the same deterministic
    content, so assertions about the summary, subtitles and mindmap stay stable. An
    address the normaliser accepted but whose shape is unknown falls back to the P1
    demo Video, keeping the historical golden-path filename ``youtube-demoP1Video.txt``.
    """
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    segments = [segment for segment in parsed.path.split("/") if segment]
    if host.endswith("douyin.com"):
        return "douyin", (segments[-1] if segments else _DEMO_DOUYIN_ID)
    if host.endswith("bilibili.com") or host == "b23.tv":
        return "bilibili", (segments[-1] if segments else "BV1demo00001")
    video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
    if not video_id and host in {"youtu.be", "www.youtu.be"}:
        video_id = segments[-1] if segments else ""
    return "youtube", (video_id or _DEMO_ID)


class DemoMediaStore:
    """Writes a tiny deterministic file and reports download/merge progress."""

    async def download(
        self,
        *,
        video: ResolvedVideo,
        format_id: str,
        dest_dir: Path,
        on_progress: Callable[[str, float], None],
    ) -> Path:
        on_progress("downloading", 0.2)
        await asyncio.sleep(0.01)
        on_progress("downloading", 0.7)
        await asyncio.sleep(0.01)
        on_progress("merging", 1.0)
        await asyncio.to_thread(dest_dir.mkdir, parents=True, exist_ok=True)
        target = Path(dest_dir) / f"demo-{format_id}.mp4"
        await asyncio.to_thread(target.write_bytes, b"demo media bytes")
        return target


class DemoSummarizer:
    """Streams a fixed summary + mindmap so SSE assertions are stable."""

    _CHUNKS = (
        "## 核心方法\n",
        "间隔重复依据遗忘曲线安排复习：一天、三天，然后逐步拉长间隔。\n\n",
        "## 关键做法\n",
        "- 先主动回忆，再核对答案。\n",
        "- 把知识拆成只含一个问题的卡片。\n",
        "- 记录复习结果，按掌握程度调整间隔。\n\n",
        "## 思维导图\n",
        "- 间隔重复\n",
        "  - 原理：遗忘曲线\n",
        "  - 做法：主动回忆、卡片化\n",
        "  - 调整：按掌握程度\n",
    )

    def stream(self, *, prompt: str) -> AsyncIterator[str]:
        async def _generate() -> AsyncIterator[str]:
            for chunk in self._CHUNKS:
                await asyncio.sleep(0.01)
                yield chunk

        return _generate()


class DemoBillingGateway:
    """Serves a deterministic offline checkout page URL for the golden path."""

    async def create_checkout(
        self,
        *,
        account_id: str,
        email: str | None,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        await asyncio.sleep(0.01)
        return CheckoutSession(id="cs_demo_checkout", url="https://checkout.demo.invalid/cs_demo")

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        """Offline replay of Stripe-style events; the golden path signs with the demo secret."""
        return verify_and_decode(payload=payload, signature_header=signature, secret=DEMO_WEBHOOK_SECRET)

    async def create_portal(self, *, provider_customer_id: str, return_url: str) -> CustomerPortal:
        """Deterministic offline customer-portal page for the golden path."""
        await asyncio.sleep(0.01)
        return CustomerPortal(url="https://portal.demo.invalid/portal_demo")


@dataclass
class DemoEmailSender:
    """In-memory inbox standing in for real email delivery in fake-adapter mode.

    The ``sent`` attribute mirrors ``tests.fakes.FakeEmailSender`` exactly: one
    naming for the delivered-mail list across test and demo seams. The Playwright
    golden path reads the verification link back out of it through the demo-only
    ``GET /api/demo/inbox`` route; nothing ever leaves the process (user story 27).
    """

    sent: list[OutboundEmail] = field(default_factory=list)

    async def send(self, message: OutboundEmail) -> None:
        logging.getLogger("app.adapters.demo").info(
            "demo_email_queued", extra={"event": "demo_email_queued", "to": message.to}
        )
        self.sent.append(message)

    def messages_for(self, to: str | None = None) -> list[OutboundEmail]:
        """Newest-first inbox view, optionally narrowed to one address."""
        messages = [message for message in self.sent if to is None or message.to == to]
        return list(reversed(messages))
