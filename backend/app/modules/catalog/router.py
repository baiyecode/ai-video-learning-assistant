"""Catalog HTTP routes: Video resolve, cached metadata and Subtitle access.

Routes here are mounted under ``/api``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Adapters
from app.deps import get_adapters, get_rate_limiter, get_session
from app.http import client_ip
from app.ratelimit import RateLimiter

from . import service, subtitles
from .schemas import ResolveResponse, ResolveVideoRequest, VideoDetailResponse

router = APIRouter(prefix="/videos", tags=["catalog"])


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_video(
    payload: ResolveVideoRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResolveResponse:
    rate_limiter.hit("videos.resolve", client_ip(request))
    return await service.resolve_video(session, adapters.video_source, adapters.clock, payload.url)


@router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video(
    video_id: str,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
) -> VideoDetailResponse:
    return await service.get_video(session, adapters.clock, video_id)


@router.get("/{video_id}/subtitles", response_model=None)
async def get_subtitles(
    video_id: str,
    format: Literal["srt", "vtt", "txt"] | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Return the selected Subtitle as JSON, or download it as SRT/VTT/TXT."""
    if format is None:
        return await subtitles.get_subtitle(session, video_id)

    export = await subtitles.export_subtitle(session, video_id, format)
    return Response(
        content=export.content,
        media_type=export.media_type,
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )
