"""Billing HTTP routes: the upgrade entry point, the customer portal, membership status and the webhook.

Routes are mounted under ``/api`` by ``main.py``. The router carries no prefix so
``/me/membership`` can live next to identity's ``/me`` while billing owns its reads.
``/billing/webhook`` is unauthenticated by design: the signature gate lives inside
the BillingGateway adapter, and the route never trusts an unsigned body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.container import Adapters
from app.deps import get_adapters, get_clock, get_current_account, get_session, get_settings
from app.modules.billing import service
from app.modules.billing.schemas import CheckoutOut, MembershipOut, PortalOut, WebhookOut
from app.modules.identity.models import Account
from app.ports import Clock

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


@router.post("/billing/portal", response_model=PortalOut, summary="Open the customer portal")
async def create_portal(
    request: Request,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_session),
    adapters: Adapters = Depends(get_adapters),
) -> PortalOut:
    """Self-service management link: card updates and invoices stay with the provider."""
    return await service.open_portal(
        session, adapters.billing_gateway, account, origin=_origin(request)
    )


@router.get("/me/membership", response_model=MembershipOut, summary="Current subscription status")
async def get_membership(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> MembershipOut:
    return await service.membership(session, account.id, now=clock.now())


@router.post(
    "/billing/webhook",
    response_model=WebhookOut,
    summary="Payment provider webhook (signature-verified, no auth)",
)
async def billing_webhook(
    request: Request,
    adapters: Adapters = Depends(get_adapters),
    session: AsyncSession = Depends(get_session),
) -> WebhookOut:
    """Verify + decode behind the port, then advance the state machine and answer 2xx.

    Any decoding or processing failure propagates as a non-2xx so the provider retries;
    the work itself is a couple of indexed SQLite writes, so the path stays fast.
    """
    body = await request.body()
    event = adapters.billing_gateway.verify_webhook(
        payload=body, signature=request.headers.get("stripe-signature", "")
    )
    await service.apply_webhook(session, adapters.clock, event)
    return WebhookOut(received=True)
