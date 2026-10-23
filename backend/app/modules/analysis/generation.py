"""Prompt construction and stream splitting for Analysis generation.

One Summarizer call yields both the summary and the mindmap: the model is asked to
write the summary and then a ``## 思维导图`` section. :class:`OutputSplitter` streams
only the summary part over SSE and holds back a small tail so a marker split across
two chunks is never leaked into the reader.
"""

from __future__ import annotations

from app.ports import BudgetLedger

MINDMAP_MARKER = "## 思维导图"
MESSAGE_ANALYSIS_FAILED = "AI 生成失败，请稍后重试"

_SOURCE_LABELS = {"manual": "人工字幕", "auto": "自动字幕"}


def prepare_subtitle_chunks(subtitle_text: str) -> tuple[list[str], bool]:
    """Seam for ticket #9: split a long Subtitle at cue boundaries.

    Returns ``(chunks, truncated)``. Today one chunk is used and nothing is dropped;
    #9 replaces this with bounded chunks plus merge/summarise logic and may set
    ``truncated`` when input beyond the model limit is skipped.
    """
    return [subtitle_text], False


def build_prompt(
    *,
    title: str,
    duration_seconds: int,
    subtitle_source: str,
    subtitle_text: str,
) -> str:
    chunks, _truncated = prepare_subtitle_chunks(subtitle_text)
    minutes = max(1, round(duration_seconds / 60))
    source_label = _SOURCE_LABELS.get(subtitle_source, "字幕")
    body = "\n\n".join(chunks)
    return (
        "你是一名中文视频学习助手。请基于下面的视频字幕，生成结构化的学习笔记。\n"
        f"视频标题：{title}\n"
        f"视频时长：约 {minutes} 分钟\n"
        f"字幕来源：{source_label}\n\n"
        "输出要求：\n"
        "1. 先用 Markdown 输出摘要，使用 ## 小标题分节，覆盖视频的主要结构与结论；\n"
        f"2. 然后单独输出一行 `{MINDMAP_MARKER}`，其下用嵌套 Markdown 列表描述视频结构，最多三层；\n"
        "3. 全部使用简体中文，只使用字幕中的信息，不要编造。\n\n"
        "字幕内容：\n"
        f"{body}"
    )


async def ensure_budget(ledger: BudgetLedger) -> None:
    """Hook for ticket #12: refuse generation when the global AI budget is exhausted.

    #12 replaces the body with ``can_spend``/``record`` calls raising
    ``budget_exhausted``; #8 deliberately has no budget policy.
    """
    del ledger


class OutputSplitter:
    """Incrementally separates summary text from the trailing mindmap section."""

    def __init__(self) -> None:
        self._raw = ""
        self._marker_index: int | None = None
        self._emitted = 0
        self._summary = ""

    @property
    def summary(self) -> str:
        """Summary text that is currently safe to persist and stream."""
        return self._summary

    @property
    def has_content(self) -> bool:
        return bool(self._raw.strip())

    def feed(self, chunk: str) -> str:
        """Append ``chunk`` and return newly available summary text (possibly empty)."""
        if not chunk:
            return ""
        self._raw += chunk

        if self._marker_index is not None:
            return ""

        index = self._raw.find(MINDMAP_MARKER)
        if index != -1:
            self._marker_index = index
            self._summary = self._raw[:index].rstrip()
            return self._take_new()

        # Hold back the longest possible partial marker so it is never emitted.
        holdback = len(MINDMAP_MARKER) - 1
        safe_end = max(self._emitted, len(self._raw) - holdback)
        self._summary = self._raw[:safe_end]
        return self._take_new()

    def _take_new(self) -> str:
        new = self._summary[self._emitted :]
        self._emitted = max(self._emitted, len(self._summary))
        return new

    def finish(self) -> tuple[str, str]:
        """Final ``(summary_markdown, mindmap_markdown)``; missing marker ⇒ empty mindmap."""
        index = self._raw.find(MINDMAP_MARKER)
        if index == -1:
            return self._raw.strip(), ""
        summary = self._raw[:index].strip()
        mindmap = self._raw[index + len(MINDMAP_MARKER) :].strip()
        return summary, mindmap
