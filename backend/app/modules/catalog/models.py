"""SQLAlchemy models for catalog (Video, Subtitle).

Video identity is global: ``(platform, platform_video_id)`` is unique, so every URL
variant of one Platform video resolves to the same row. The formats/subtitles columns
are point-in-time snapshots; subtitle *content* is owned by ticket #4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("platform", "platform_video_id", name="uq_videos_platform_video_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    platform_video_id: Mapped[str] = mapped_column(String(64))

    title: Mapped[str] = mapped_column(String(512))
    duration_seconds: Mapped[int]
    webpage_url: Mapped[str] = mapped_column(String(2048))
    uploader: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Surfaced in the API now; the full DRM/members policy lands in #14.
    is_drm: Mapped[bool] = mapped_column(default=False)
    is_members_only: Mapped[bool] = mapped_column(default=False)

    # Point-in-time snapshot of the Platform's format list (10-minute TTL).
    formats_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    formats_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Subtitle availability only (language + source type); #4 stores the content.
    subtitles_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
