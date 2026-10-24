"""Read-only Analysis history queries scoped to a single Account.

Kept apart from ``service`` so list shaping (join Video, snippet, ordering) never
collides with the create/read use-cases. Every query filters by ``account_id``; rows
of another Account are unreachable by construction, even with a guessed id.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Video
from app.timeutil import as_utc

from .models import Analysis
from .schemas import AnalysisHistoryItemOut, AnalysisHistoryVideoOut

SNIPPET_MAX_CHARS = 120

# Drop the most common block markers so a one-line list preview reads as prose.
_BLOCK_MARKERS = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*)", re.MULTILINE)
_WHITESPACE = re.compile(r"\s+")


def _iso(value: datetime | None) -> str | None:
    aware = as_utc(value)
    return aware.isoformat() if aware is not None else None


def summary_snippet(markdown: str | None, *, limit: int = SNIPPET_MAX_CHARS) -> str:
    """A short, single-line preview of the stored summary."""
    text = _WHITESPACE.sub(" ", _BLOCK_MARKERS.sub("", markdown or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def to_history_item(analysis: Analysis, video: Video | None) -> AnalysisHistoryItemOut:
    video_out = (
        AnalysisHistoryVideoOut(
            id=video.id,
            title=video.title,
            platform=video.platform,
            thumbnail_url=video.thumbnail_url,
        )
        if video is not None
        else None
    )
    return AnalysisHistoryItemOut(
        id=analysis.id,
        video_id=analysis.video_id,
        status=analysis.status,  # type: ignore[arg-type]
        subtitle_source=analysis.subtitle_source,  # type: ignore[arg-type]
        truncated=bool(analysis.truncated),
        summary_snippet=summary_snippet(analysis.summary_markdown),
        error_code=analysis.error_code,
        created_at=_iso(analysis.created_at) or "",
        completed_at=_iso(analysis.completed_at),
        video=video_out,
    )


async def list_analyses(
    session: AsyncSession, account_id: str
) -> list[AnalysisHistoryItemOut]:
    """The Account's Analyses, newest first. Never reads another Account's rows."""
    rows = (
        await session.execute(
            select(Analysis, Video)
            .outerjoin(Video, Video.id == Analysis.video_id)
            .where(Analysis.account_id == account_id)
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        )
    ).all()
    return [to_history_item(analysis, video) for analysis, video in rows]
