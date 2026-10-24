"""Billing domain logic: the upgrade entry point.

State policy (spec): the subscription record is only advanced by gateway webhooks,
never guessed here. Creating a checkout therefore stores nothing - it just asks the
port for a hosted payment page.
"""

from __future__ import annotations

from app.config import Settings
from app.modules.billing.schemas import CheckoutOut
from app.modules.identity.models import Account
from app.ports import BillingGateway


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
