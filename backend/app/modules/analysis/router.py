"""Analysis HTTP routes: create, list, detail and the SSE stream.

Routes here are mounted under ``/api``. Tickets #8-#11 add endpoints to ``router``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/analyses", tags=["analysis"])
