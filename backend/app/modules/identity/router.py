"""Identity HTTP routes: register, login, refresh, logout and ``/api/me``.

Routes here are mounted under ``/api``. Ticket #7 adds endpoints to ``router``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["identity"])
