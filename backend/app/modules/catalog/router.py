"""Catalog HTTP routes: Video resolve and cached metadata.

Routes here are mounted under ``/api``. Ticket #4 adds Subtitle endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Adapters
from app.deps import get_adapters, get_session

from . import service
from .schemas import ResolveResponse, ResolveVideoRequest, VideoDetailResponse

router = APIRouter(prefix="/videos", tags=["catalog"])


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_video(
    payload: ResolveVideoRequest,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
) -> ResolveResponse:
    return await service.resolve_video(session, adapters.video_source, adapters.clock, payload.url)


@router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video(
    video_id: str,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
) -> VideoDetailResponse:
    return await service.get_video(session, adapters.clock, video_id)
