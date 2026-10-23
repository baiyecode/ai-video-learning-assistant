"""Pydantic request/response schemas for the Analysis HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateAnalysisRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=64)
    # Re-analysing an already completed Video consumes one more Quota (#11 adds the
    # user-facing confirmation before sending this).
    force: bool = False


class AnalysisVideoOut(BaseModel):
    id: str
    title: str
    platform: str
    duration_seconds: int
    thumbnail_url: str | None = None


class AnalysisErrorOut(BaseModel):
    code: str
    message: str


class AnalysisOut(BaseModel):
    id: str
    video_id: str
    status: Literal["pending", "streaming", "completed", "failed"]
    summary_markdown: str
    mindmap_markdown: str
    subtitle_source: Literal["manual", "auto"]
    truncated: bool
    error: AnalysisErrorOut | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    video: AnalysisVideoOut | None = None


class QuotaOut(BaseModel):
    daily_limit: int
    used: int
    remaining: int
    resets_at: str
