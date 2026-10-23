"""Pydantic request/response schemas for the Download HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateDownloadRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=64)
    format_id: str = Field(min_length=1, max_length=128)


class DownloadErrorOut(BaseModel):
    code: str
    message: str


class DownloadOut(BaseModel):
    """Task state. ``download_url`` is a signed, same-origin temporary link."""

    id: str
    video_id: str
    format_id: str
    status: str
    progress: float
    error: DownloadErrorOut | None = None
    attempts: int
    file_name: str | None = None
    file_size: int | None = None
    created_at: datetime
    updated_at: datetime
    ready_at: datetime | None = None
    download_url: str | None = None
    url_expires_at: datetime | None = None
    file_expires_at: datetime | None = None
    can_retry: bool = False
    # 1-based FIFO position while ``queued``; ``None`` once running or terminal.
    queue_position: int | None = None
