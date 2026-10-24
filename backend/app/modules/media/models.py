"""SQLAlchemy models for media (Download jobs).

A Download is an anonymous-capable attempt to produce a temporary file for one Video
format. It deliberately keeps no subtitle/analysis data: the file lives for one hour,
the signed URL for fifteen minutes, and the row is a short-lived delivery record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


class DownloadStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    MERGING = "merging"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


ACTIVE_STATUSES = frozenset({DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.MERGING})
TERMINAL_STATUSES = frozenset({DownloadStatus.READY, DownloadStatus.FAILED, DownloadStatus.EXPIRED})


class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    video_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("videos.id", ondelete="CASCADE"), index=True, nullable=False
    )
    format_id: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=DownloadStatus.QUEUED, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Number of manual retries already spent on this task.
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Absolute path on the server; never exposed through the API.
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    visitor_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
