"""Catalog HTTP routes: Video resolve, cached metadata and Subtitle export.

Routes here are mounted under ``/api``. Tickets #3/#4 add endpoints to ``router``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/videos", tags=["catalog"])
