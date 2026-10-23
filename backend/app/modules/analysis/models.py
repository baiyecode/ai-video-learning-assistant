"""SQLAlchemy models for analysis: Analysis and daily QuotaUsage.

An Analysis belongs to one Account and pins the Subtitle version it was generated
from, so later Subtitle updates never rewrite an existing result (ADR-0002).

Concurrency contract
--------------------
``uq_analyses_active_account_video`` is a *partial* unique index covering only
``pending``/``streaming`` rows. It makes "one in-progress Analysis per Account and
Video" a database invariant: two simultaneous create requests cannot both insert,
so a double click reuses the winner instead of reserving a second Quota.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_STATUSES = (AnalysisStatus.PENDING.value, AnalysisStatus.STREAMING.value)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index(
            "uq_analyses_active_account_video",
            "account_id",
            "video_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'streaming')"),
        ),
        Index("ix_analyses_account_created", "account_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    subtitle_id: Mapped[str | None] = mapped_column(
        ForeignKey("subtitles.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(16), default=AnalysisStatus.PENDING.value, index=True)
    summary_markdown: Mapped[str] = mapped_column(Text, default="")
    mindmap_markdown: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Snapshot of the Subtitle version used, so the UI can show 人工/自动 even if
    # the Video's Subtitle is re-selected later.
    subtitle_source: Mapped[str] = mapped_column(String(16), default="manual")
    # True when the Subtitle exceeded the configured input budget and only chunks
    # spread across the timeline (first/middle/last) were summarised (ticket #9).
    truncated: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuotaUsage(Base):
    """Per-Account per-Asia/Shanghai-day Quota counters.

    ``reserved`` counts in-progress Analyses, ``consumed`` counts successful ones.
    A row is created on the first reservation of the day.
    """

    __tablename__ = "quota_usage"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    # (account_id, day) is the composite primary key, i.e. the unique key per day.
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    reserved: Mapped[int] = mapped_column(default=0)
    consumed: Mapped[int] = mapped_column(default=0)
