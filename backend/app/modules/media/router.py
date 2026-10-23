"""Media HTTP routes: Download creation, status, retry and signed file delivery.

Routes here are mounted under ``/api``. Ticket #6 adds rate limits, concurrency caps
and Range support on top of these endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.container import Adapters
from app.deps import get_adapters, get_optional_account, get_session, get_settings
from app.modules.identity.models import Account

from . import service
from .manager import DownloadManager
from .schemas import CreateDownloadRequest, DownloadOut

router = APIRouter(prefix="/downloads", tags=["media"])

_MANAGER_STATE_KEY = "download_manager"


def get_download_manager(request: Request) -> DownloadManager:
    """Lazily attach the in-process queue to ``app.state`` (keeps ``main.py`` untouched)."""
    manager: DownloadManager | None = getattr(request.app.state, _MANAGER_STATE_KEY, None)
    if manager is None:
        state = request.app.state
        manager = DownloadManager(
            sessionmaker=state.sessionmaker,
            adapters=state.adapters,
            settings=state.settings,
        )
        setattr(state, _MANAGER_STATE_KEY, manager)
    return manager


@router.post("", response_model=DownloadOut, status_code=202)
async def create_download(
    payload: CreateDownloadRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    account: Account | None = Depends(get_optional_account),
) -> DownloadOut:
    download = await service.create_download(
        session,
        adapters.clock,
        video_id=payload.video_id,
        format_id=payload.format_id,
        visitor_ip=_client_ip(request),
        account_id=account.id if account is not None else None,
    )
    get_download_manager(request).submit(download.id)
    return service.to_out(download, download_url=None)


@router.get("/{download_id}", response_model=DownloadOut)
async def get_download(
    download_id: str,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    settings: Settings = Depends(get_settings),
) -> DownloadOut:
    return await service.get_download(session, settings, adapters.clock, download_id)


@router.post("/{download_id}/retry", response_model=DownloadOut, status_code=202)
async def retry_download(
    download_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
) -> DownloadOut:
    download = await service.prepare_retry(session, adapters.clock, download_id)
    get_download_manager(request).submit(download.id)
    return service.to_out(download, download_url=None)


@router.get("/{download_id}/file", response_class=FileResponse)
async def download_file(
    download_id: str,
    expires: int = Query(ge=0),
    sig: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    path, file_name = await service.resolve_file(
        session,
        adapters.clock,
        download_id=download_id,
        expires_at=expires,
        signature=sig,
        secret=settings.secret_key,
    )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=file_name,
        headers={"Cache-Control": "private, no-store"},
    )


def _client_ip(request: Request) -> str | None:
    """Honour the reverse proxy's first hop, fall back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = request.client
    return client.host if client is not None else None
