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

from app.ports import OutboundEmail, ResolvedVideo, SubtitlePayload, SubtitleTrack, VideoFormat

_DEMO_ID = "demoP1Video"
_DEMO_TITLE = "演示视频：从零理解间隔重复"
_DEMO_SUBTITLE = (
    "间隔重复是一种利用遗忘曲线安排复习的学习方法。"
    "第一次复习安排在一天后，第二次三天后，随后逐渐拉长间隔。"
    "每次复习时先主动回忆，再核对答案，效果远好于被动重读。"
    "把知识拆成小卡片，并只保留一个明确问题，可以减少记忆负担。"
    "坚持记录复习结果，让算法根据掌握程度调整下一次出现的时间。"
)


class DemoVideoSource:
    """Resolves any supported URL to one canned, deterministic Video."""

    async def resolve(self, url: str) -> ResolvedVideo:
        return ResolvedVideo(
            platform="youtube",
            platform_video_id=_DEMO_ID,
            title=_DEMO_TITLE,
            duration_seconds=300,
            webpage_url="https://www.youtube.com/watch?v=demoP1Video",
            uploader="演示作者",
            thumbnail_url=None,
            formats=(
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
            ),
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


@dataclass
class DemoEmailSender:
    """In-memory inbox standing in for real email delivery in fake-adapter mode.

    The Playwright golden path reads the verification link back out of ``inbox``;
    nothing ever leaves the process (user story 27).
    """

    inbox: list[OutboundEmail] = field(default_factory=list)

    async def send(self, message: OutboundEmail) -> None:
        logging.getLogger("app.adapters.demo").info(
            "demo_email_queued", extra={"event": "demo_email_queued", "to": message.to}
        )
        self.inbox.append(message)
