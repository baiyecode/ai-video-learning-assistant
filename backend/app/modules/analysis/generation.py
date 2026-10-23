"""Prompt construction and stream splitting for Analysis generation.

Long Subtitles are split only at cue boundaries into chunks bounded by a character
budget. A one-chunk Subtitle keeps a single direct call; otherwise every chunk is
summarised first (map) and one merge call (reduce) writes the final summary plus the
``## 思维导图`` section. When the total input exceeds its budget, chunks spread over
the timeline (beginning/middle/end) are kept and the Analysis is flagged truncated.

The final call yields both the summary and the mindmap; :class:`OutputSplitter`
streams only the summary part over SSE and holds back a small tail so a marker split
across two chunks is never leaked into the reader.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.errors import AppError, ErrorCode
from app.ports import BudgetLedger, Clock
from app.timeutil import next_shanghai_midnight

MINDMAP_MARKER = "## 思维导图"
MESSAGE_ANALYSIS_FAILED = "AI 生成失败，请稍后重试"
MESSAGE_BUDGET_EXHAUSTED = "今日 AI 预算已用完，请于 {reset}（北京时间）后再试"

_SOURCE_LABELS = {"manual": "人工字幕", "auto": "自动字幕"}


@dataclass(frozen=True, slots=True)
class Cue:
    """One Subtitle cue. Chunking never splits a cue, so its text stays whole."""

    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    """A contiguous run of whole cues plus its position in the full timeline."""

    cues: tuple[Cue, ...]
    index: int
    count: int

    @property
    def text(self) -> str:
        return "\n".join(cue.text for cue in self.cues)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def start(self) -> float:
        return self.cues[0].start

    @property
    def end(self) -> float:
        return self.cues[-1].end


def cues_from_stored(stored: Sequence[dict[str, Any]] | None, *, fallback_text: str) -> list[Cue]:
    """Normalise the persisted ``cues_json`` shape; fall back to the plain text."""
    cues: list[Cue] = []
    for item in stored or ():
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = float(item.get("start", 0.0))
        cues.append(Cue(start=start, end=max(start, float(item.get("end", start))), text=text))
    if cues:
        return cues
    text = fallback_text.strip()
    return [Cue(start=0.0, end=0.0, text=text)] if text else []


def plan_chunks(cues: Sequence[Cue], *, max_chars: int) -> list[Chunk]:
    """Pack whole cues into chunks of at most ``max_chars`` characters.

    A single cue longer than the budget becomes its own chunk rather than being cut.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    groups: list[list[Cue]] = []
    current: list[Cue] = []
    current_chars = 0
    for cue in cues:
        extra = len(cue.text) + (1 if current else 0)
        if current and current_chars + extra > max_chars:
            groups.append(current)
            current = [cue]
            current_chars = len(cue.text)
        else:
            current.append(cue)
            current_chars += extra
    if current:
        groups.append(current)

    count = len(groups)
    return [
        Chunk(cues=tuple(group), index=index, count=count)
        for index, group in enumerate(groups)
    ]


def _spread(count: int, picks: int) -> list[int]:
    """Evenly spaced chunk indices inclusive of the first and last."""
    if picks <= 1:
        return [count // 2]
    return sorted({round(step * (count - 1) / (picks - 1)) for step in range(picks)})


def select_chunks(
    chunks: Sequence[Chunk], *, max_input_chars: int
) -> tuple[list[Chunk], bool]:
    """Pick chunks that fit ``max_input_chars``, spread across the whole timeline.

    Returns ``(chunks, truncated)``. When the Subtitle is too long the tail is never
    dropped silently: the selection keeps the beginning, the middle and the end and
    the caller reports ``truncated`` to the user.
    """
    if max_input_chars <= 0:
        raise ValueError("max_input_chars must be positive")
    total = sum(chunk.char_count for chunk in chunks)
    if total <= max_input_chars:
        return list(chunks), False

    for picks in range(len(chunks), 0, -1):
        indices = _spread(len(chunks), picks)
        selected = [chunks[index] for index in indices]
        if sum(chunk.char_count for chunk in selected) <= max_input_chars:
            return selected, True
    # Even a single chunk exceeds the limit (one huge cue). Keep the middle of the
    # video rather than an arbitrary head, and still flag the result as truncated.
    return [chunks[len(chunks) // 2]] if chunks else [], True


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    """Prompts for one Analysis.

    ``chunk_prompts`` is empty when the whole Subtitle fits one call
    (``direct_prompt`` then carries it). Otherwise every chunk is summarised first and
    :func:`build_merge_prompt` reduces the partial summaries into the final result.
    """

    title: str
    duration_seconds: int
    subtitle_source: str
    chunk_prompts: tuple[str, ...]
    segment_labels: tuple[str, ...]
    direct_prompt: str | None
    truncated: bool

    @property
    def needs_merge(self) -> bool:
        return bool(self.chunk_prompts)


def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _video_context(*, title: str, duration_seconds: int, subtitle_source: str) -> str:
    minutes = max(1, round(duration_seconds / 60))
    source_label = _SOURCE_LABELS.get(subtitle_source, "字幕")
    return f"视频标题：{title}\n视频时长：约 {minutes} 分钟\n字幕来源：{source_label}"


def _direct_prompt(
    *,
    title: str,
    duration_seconds: int,
    subtitle_source: str,
    body: str,
    truncated: bool,
) -> str:
    note = "（注意：字幕较长，以下仅为按时间顺序抽取的部分内容。）\n\n" if truncated else ""
    context = _video_context(
        title=title, duration_seconds=duration_seconds, subtitle_source=subtitle_source
    )
    return (
        "你是一名中文视频学习助手。请基于下面的视频字幕，生成结构化的学习笔记。\n"
        f"{context}\n\n"
        f"{note}"
        "输出要求：\n"
        "1. 先用 Markdown 输出摘要，使用 ## 小标题分节，覆盖视频的主要结构与结论；\n"
        f"2. 然后单独输出一行 `{MINDMAP_MARKER}`，其下用嵌套 Markdown 列表描述视频结构，最多三层；\n"
        "3. 全部使用简体中文，只使用字幕中的信息，不要编造。\n\n"
        "字幕内容：\n"
        f"{body}"
    )


def _chunk_prompt(
    *,
    title: str,
    duration_seconds: int,
    subtitle_source: str,
    chunk: Chunk,
) -> str:
    context = _video_context(
        title=title, duration_seconds=duration_seconds, subtitle_source=subtitle_source
    )
    return (
        "你是一名中文视频学习助手。下面是一段视频字幕中的第 "
        f"{chunk.index + 1}/{chunk.count} 段（{_timestamp(chunk.start)}–{_timestamp(chunk.end)}）。\n"
        f"{context}\n\n"
        "请用简体中文提炼这一段的 3-6 条要点，保留关键结论、数字与专有名词，"
        "不要编造，不要输出思维导图。\n\n"
        "字幕片段：\n"
        f"{chunk.text}"
    )


def build_plan(
    *,
    title: str,
    duration_seconds: int,
    subtitle_source: str,
    cues: Sequence[Cue],
    chunk_chars: int,
    max_input_chars: int,
) -> GenerationPlan:
    """Split at cue boundaries and choose map-reduce or a single direct call."""
    chunks = plan_chunks(cues, max_chars=chunk_chars)
    selected, truncated = select_chunks(chunks, max_input_chars=max_input_chars)
    if not selected:
        raise ValueError("Subtitle has no content to analyse")

    if len(selected) == 1:
        return GenerationPlan(
            title=title,
            duration_seconds=duration_seconds,
            subtitle_source=subtitle_source,
            chunk_prompts=(),
            segment_labels=(),
            direct_prompt=_direct_prompt(
                title=title,
                duration_seconds=duration_seconds,
                subtitle_source=subtitle_source,
                body=selected[0].text,
                truncated=truncated,
            ),
            truncated=truncated,
        )

    chunk_prompts = tuple(
        _chunk_prompt(
            title=title,
            duration_seconds=duration_seconds,
            subtitle_source=subtitle_source,
            chunk=chunk,
        )
        for chunk in selected
    )
    labels = tuple(
        f"第 {chunk.index + 1}/{chunk.count} 段（{_timestamp(chunk.start)}–{_timestamp(chunk.end)}）"
        for chunk in selected
    )
    return GenerationPlan(
        title=title,
        duration_seconds=duration_seconds,
        subtitle_source=subtitle_source,
        chunk_prompts=chunk_prompts,
        segment_labels=labels,
        direct_prompt=None,
        truncated=truncated,
    )


def planned_call_count(plan: GenerationPlan) -> int:
    """Every Summarizer call the plan will make: one per chunk plus the merge."""
    return len(plan.chunk_prompts) + 1


def build_merge_prompt(plan: GenerationPlan, *, partial_summaries: Sequence[str]) -> str:
    """Reduce the per-chunk summaries into the final summary + mindmap call."""
    if len(partial_summaries) != len(plan.segment_labels):
        raise ValueError("one partial summary per selected chunk is required")
    context = _video_context(
        title=plan.title,
        duration_seconds=plan.duration_seconds,
        subtitle_source=plan.subtitle_source,
    )
    blocks = "\n\n".join(
        f"### {label}\n{summary.strip()}"
        for label, summary in zip(plan.segment_labels, partial_summaries, strict=True)
    )
    coverage = (
        "输入字幕较长，已按时间顺序抽取开头、中段和结尾的片段。\n"
        if plan.truncated
        else ""
    )
    return (
        "你是一名中文视频学习助手。下面是同一视频按时间顺序分段摘要的结果。\n"
        f"{context}\n\n"
        f"{coverage}"
        "请将这些分段摘要归并成一篇结构化的学习笔记，覆盖视频的开头、中段与结尾，"
        "不要遗漏任何分段的要点，也不要编造。\n\n"
        "输出要求：\n"
        "1. 先用 Markdown 输出摘要，使用 ## 小标题分节，覆盖视频的主要结构与结论；\n"
        f"2. 然后单独输出一行 `{MINDMAP_MARKER}`，其下用嵌套 Markdown 列表描述视频结构，最多三层；\n"
        "3. 全部使用简体中文，只使用分段摘要中的信息。\n\n"
        "分段摘要：\n"
        f"{blocks}"
    )


def budget_reset_at(clock: Clock) -> datetime:
    """When the daily AI budget renews: the next Asia/Shanghai midnight."""
    return next_shanghai_midnight(clock.now())


async def ensure_budget(
    ledger: BudgetLedger,
    *,
    estimated_usd: float,
    clock: Clock,
    daily_budget_usd: float,
) -> None:
    """Raise ``budget_exhausted`` when one more call would cross the daily budget.

    Called when a genuinely new Analysis is created (before Quota is reserved) and
    again right before generation. Viewing completed Analyses never calls this.
    """
    if await ledger.can_spend(estimated_usd):
        return

    reset_at = budget_reset_at(clock)
    raise AppError(
        429,
        ErrorCode.BUDGET_EXHAUSTED,
        MESSAGE_BUDGET_EXHAUSTED.format(reset=reset_at.strftime("%Y-%m-%d %H:%M")),
        {
            "daily_budget_usd": daily_budget_usd,
            "estimated_usd": estimated_usd,
            "resets_at": reset_at.isoformat(),
        },
    )


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
