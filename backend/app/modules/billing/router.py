"""Billing HTTP routes: the upgrade entry point and membership status.

Routes are mounted under ``/api`` by ``main.py``. The router carries no prefix so
``/me/membership`` can live next to identity's ``/me`` while billing owns its reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.container import Adapters
from app.deps import get_adapters, get_current_account, get_session, get_settings
from app.modules.billing import service
from app.modules.billing.schemas import CheckoutOut, MembershipOut
from app.modules.identity.models import Account

router = APIRouter(tags=["billing"])


def _origin(request: Request) -> str:
    """Browser origin used to build Stripe's success/cancel redirects."""
    header = request.headers.get("origin")
    if header:
        return header.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.post("/billing/checkout", response_model=CheckoutOut, summary="Start a checkout session")
async def create_checkout(
    request: Request,
    account: Account = Depends(get_current_account),
    adapters: Adapters = Depends(get_adapters),
    settings: Settings = Depends(get_settings),
) -> CheckoutOut:
    return await service.open_checkout(
        adapters.billing_gateway, settings, account, origin=_origin(request)
    )


@router.get("/me/membership", response_model=MembershipOut, summary="Current subscription status")
async def get_membership(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_session),
) -> MembershipOut:
    return await service.membership(session, account.id)
