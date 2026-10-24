"""Billing HTTP routes: the upgrade entry point and membership status.

Routes are mounted under ``/api`` by ``main.py``. The router carries no prefix so
``/me/membership`` can live next to identity's ``/me`` while billing owns its reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_account
from app.modules.identity.models import Account

router = APIRouter(tags=["billing"])


@router.post("/billing/checkout", summary="Start a hosted checkout session")
async def create_checkout(
    account: Account = Depends(get_current_account),
) -> dict:
    raise NotImplementedError
