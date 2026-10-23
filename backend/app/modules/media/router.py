"""Media HTTP routes: Download creation, status, retry and signed file delivery.

Routes here are mounted under ``/api``. Ticket #6 adds rate limits, concurrency caps
and Range support on top of these endpoints.
"""

from __future__ import annotations

from collections.abc import Collection

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.container import Adapters
from app.deps import get_adapters, get_optional_account, get_rate_limiter, get_session, get_settings
from app.http import client_ip
from app.modules.identity.models import Account
from app.ratelimit import RateLimiter

from . import service
from .manager import DownloadManager
from .schemas import CreateDownloadRequest, DownloadOut

router = APIRouter(prefix="/downloads", tags=["media"])


def get_download_manager(request: Request) -> DownloadManager:
    """The queue the application lifespan started and is shutting down."""
    return request.app.state.download_manager


async def _start_manager(
    request: Request, *, exclude_ids: Collection[str] = ()
) -> DownloadManager:
    """Start the manager (recovery + cleanup) before it accepts the given rows."""
    manager = get_download_manager(request)
    await manager.start(exclude_ids=exclude_ids)
    return manager


@router.post("", response_model=DownloadOut, status_code=202)
async def create_download(
    payload: CreateDownloadRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    settings: Settings = Depends(get_settings),
    account: Account | None = Depends(get_optional_account),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> DownloadOut:
    # Per-IP minute limit (#12) runs before #6's hourly/queue caps.
    visitor_ip = client_ip(request)
    rate_limiter.hit("downloads.create", visitor_ip)
    download = await service.create_download(
        session,
        settings,
        adapters.clock,
        video_id=payload.video_id,
        format_id=payload.format_id,
        visitor_ip=visitor_ip,
        account_id=account.id if account is not None else None,
    )
    # The freshly created row is not "interrupted work" from a previous process.
    manager = await _start_manager(request, exclude_ids=(download.id,))
    manager.submit(
        download.id,
        account_id=download.account_id,
        visitor_ip=download.visitor_ip,
    )
    out = service.to_out(download, download_url=None)
    out.queue_position = manager.queue_position(download.id)
    return out


@router.get("/{download_id}", response_model=DownloadOut)
async def get_download(
    download_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    settings: Settings = Depends(get_settings),
    account: Account | None = Depends(get_optional_account),
) -> DownloadOut:
    out = await service.get_download(
        session,
        settings,
        adapters.clock,
        download_id,
        account_id=account.id if account is not None else None,
        visitor_ip=client_ip(request),
    )
    out.queue_position = get_download_manager(request).queue_position(download_id)
    return out


@router.post("/{download_id}/retry", response_model=DownloadOut, status_code=202)
async def retry_download(
    download_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
    account: Account | None = Depends(get_optional_account),
) -> DownloadOut:
    download = await service.prepare_retry(
        session,
        adapters.clock,
        download_id,
        account_id=account.id if account is not None else None,
        visitor_ip=client_ip(request),
    )
    manager = await _start_manager(request, exclude_ids=(download.id,))
    manager.submit(
        download.id,
        account_id=download.account_id,
        visitor_ip=download.visitor_ip,
    )
    out = service.to_out(download, download_url=None)
    out.queue_position = manager.queue_position(download.id)
    return out


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
