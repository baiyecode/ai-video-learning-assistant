"""Ops routes: health today, metrics/backups later (ticket #13).

This router is mounted at the application root (no ``/api`` prefix) so ``/health`` stays
public and cheap for load balancers. Any future ``/api`` route belongs here with its full
path (``@router.get("/api/ops/...")``) — do not edit ``main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from app import __version__
from app.config import Settings
from app.deps import get_settings

from .health import check_database, check_disk, check_process

router = APIRouter(tags=["ops"])


@router.get("/health", summary="Service, database and disk health")
async def health(request: Request, settings: Settings = Depends(get_settings)) -> JSONResponse:
    checks = {
        "database": await check_database(request.app.state.sessionmaker),
        "disk": check_disk(settings.media_dir),
        "process": check_process(),
    }
    healthy = all(check["ok"] for check in checks.values())
    payload = {
        "status": "ok" if healthy else "degraded",
        "service": settings.service_name,
        "version": __version__,
        "checks": checks,
    }
    return JSONResponse(
        payload,
        status_code=200 if healthy else 503,
        headers={"Cache-Control": "no-store"},
    )
