"""Ops routes: health today, metrics/backups later (ticket #13).

This router is mounted at the application root (no ``/api`` prefix) so ``/health`` stays
public and cheap for load balancers. Any future ``/api`` route belongs here with its full
path (``@router.get("/api/ops/...")``) — do not edit ``main.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import JSONResponse

from app import __version__
from app.config import Settings
from app.deps import get_settings

logger = logging.getLogger("app.ops.health")

router = APIRouter(tags=["ops"])


async def _database_is_available(sessionmaker: async_sessionmaker[AsyncSession]) -> bool:
    try:
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health must report any failure, not raise
        logger.warning("health_database_check_failed", exc_info=True)
        return False


def _disk_is_writable(directory: Path) -> bool:
    probe = directory / f".health-{uuid4().hex}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        return True
    except OSError:
        logger.warning("health_disk_check_failed", exc_info=True)
        return False
    finally:
        probe.unlink(missing_ok=True)


@router.get("/health", summary="Service, database and disk health")
async def health(request: Request, settings: Settings = Depends(get_settings)) -> JSONResponse:
    checks = {
        "database": "ok" if await _database_is_available(request.app.state.sessionmaker) else "error",
        "disk": "ok" if _disk_is_writable(settings.data_dir) else "error",
    }
    healthy = all(value == "ok" for value in checks.values())
    payload = {
        "status": "ok" if healthy else "degraded",
        "service": settings.service_name,
        "version": __version__,
        "checks": checks,
    }
    return JSONResponse(payload, status_code=200 if healthy else 503)
