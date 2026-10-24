"""Billing domain logic: the upgrade entry point, the membership read and the webhook state machine.

State policy (spec): the subscription record is only advanced by gateway webhooks,
never guessed elsewhere. Creating a checkout therefore stores nothing - it just asks the
port for a hosted payment page - and membership is a pure read of the record.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.modules.billing.models import BillingEvent, Subscription, SubscriptionStatus
from app.modules.billing.schemas import CheckoutOut, MembershipOut
from app.modules.identity.models import Account
from app.ports import BillingGateway, Clock, WebhookEvent
from app.timeutil import required_utc

logger = logging.getLogger("app.modules.billing")

STATUS_FREE = "free"
"""Membership status for an Account with no subscription record."""

CHECKOUT_COMPLETED = "checkout.session.completed"
"""The one event this ticket's state machine acts on (spec: payment success takes effect)."""


def _new_id() -> str:
    return str(uuid4())


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


async def apply_webhook(session: AsyncSession, clock: Clock, event: WebhookEvent) -> None:
    """Advance the subscription state machine with one verified domain event.

    The ``BillingEvent`` unique ``event_id`` is claimed first: losing the conflict means
    Stripe is redelivering an already-processed event, so nothing changes and the caller
    still answers 2xx. Slice scope (P2-02): ``checkout.session.completed`` makes the
    Account Active with the recorded period end; every other event type is recorded
    only (the rest of the state machine ships with P2-04).
    """
    claim = await session.execute(
        sqlite_insert(BillingEvent)
        .values(
            id=_new_id(),
            event_id=event.event_id,
            type=event.type,
            created=event.created,
            processed_at=clock.now(),
            account_id=event.account_id,
            stripe_subscription_id=event.stripe_subscription_id,
            applied=False,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    if claim.rowcount == 0:
        logger.info(
            "billing_event_duplicate_ignored",
            extra={
                "event": "billing_event_duplicate_ignored",
                "event_id": event.event_id,
                "event_type": event.type,
                "outcome": "duplicate",
            },
        )
        return
    applied = await _transition(session, event)
    if applied:
        await session.execute(
            update(BillingEvent).where(BillingEvent.event_id == event.event_id).values(applied=True)
        )
    await session.commit()


async def _transition(session: AsyncSession, event: WebhookEvent) -> bool:
    """Apply the state change this event type owns; True when state moved."""
    if event.type != CHECKOUT_COMPLETED or not event.account_id:
        return False
    if await session.get(Account, event.account_id) is None:
        return False
    subscription = await session.scalar(
        select(Subscription).where(Subscription.account_id == event.account_id)
    )
    if subscription is None:
        subscription = Subscription(
            account_id=event.account_id,
            stripe_customer_id=event.stripe_customer_id,
            stripe_subscription_id=event.stripe_subscription_id or event.event_id,
            status=SubscriptionStatus.ACTIVE.value,
            current_period_end=event.current_period_end,
            price_id=event.price_id or "",
        )
        session.add(subscription)
    else:
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.current_period_end = event.current_period_end
        if event.stripe_subscription_id:
            subscription.stripe_subscription_id = event.stripe_subscription_id
        if event.stripe_customer_id:
            subscription.stripe_customer_id = event.stripe_customer_id
        if event.price_id:
            subscription.price_id = event.price_id
    logger.info(
        "billing_membership_changed",
        extra={
            "event": "billing_membership_changed",
            "event_id": event.event_id,
            "event_type": event.type,
            "account_id": event.account_id,
            "subscription_status": SubscriptionStatus.ACTIVE.value,
            "outcome": "applied",
        },
    )
    return True
