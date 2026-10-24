"""Billing domain logic: the upgrade entry point and the membership read.

State policy (spec): the subscription record is only advanced by gateway webhooks,
never guessed here. Creating a checkout therefore stores nothing - it just asks the
port for a hosted payment page - and membership is a pure read of the record.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.modules.billing.models import Subscription
from app.modules.billing.schemas import CheckoutOut, MembershipOut
from app.modules.identity.models import Account
from app.ports import BillingGateway
from app.timeutil import required_utc

STATUS_FREE = "free"
"""Membership status for an Account with no subscription record."""


async def open_checkout(
    gateway: BillingGateway,
    settings: Settings,
    account: Account,
    *,
    origin: str,
) -> CheckoutOut:
    """Create a subscription Checkout Session and surface its URL to the browser."""
    checkout = await gateway.create_checkout(
        account_id=account.id,
        email=account.email,
        price_id=settings.stripe_price_id,
        success_url=f"{origin}/?checkout=success",
        cancel_url=f"{origin}/?checkout=cancelled",
    )
    return CheckoutOut(url=checkout.url)


async def membership(session: AsyncSession, account_id: str) -> MembershipOut:
    """The Account's subscription truth, as stored by webhooks (never recomputed)."""
    subscription = await session.scalar(
        select(Subscription).where(Subscription.account_id == account_id)
    )
    if subscription is None:
        return MembershipOut(status=STATUS_FREE, period_end=None, portal_url=None)
    return MembershipOut(
        status=subscription.status,
        period_end=(
            required_utc(subscription.current_period_end).isoformat()
            if subscription.current_period_end is not None
            else None
        ),
        portal_url=None,
    )
