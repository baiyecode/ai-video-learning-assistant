"""Media HTTP routes: Download creation, status, retry and file delivery.

Routes here are mounted under ``/api``. Tickets #5/#6 add endpoints to ``router``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/downloads", tags=["media"])
