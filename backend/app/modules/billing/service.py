"""Billing domain logic: the upgrade entry point, the membership read and the webhook state machine.

State policy (spec): the subscription record is only advanced by gateway webhooks,
never guessed elsewhere. Creating a checkout therefore stores nothing - it just asks the
port for a hosted payment page - and membership is a pure read of the record.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.modules.billing.models import BillingEvent, Subscription, SubscriptionStatus, is_vip
from app.modules.billing.schemas import CheckoutOut, MembershipOut
from app.modules.identity.models import Account
from app.ports import BillingGateway, Clock, WebhookEvent
from app.timeutil import required_utc

logger = logging.getLogger("app.modules.billing")

STATUS_FREE = "free"
"""Membership status for an Account with no subscription record."""

CHECKOUT_COMPLETED = "checkout.session.completed"
"""The event that grants a membership: the Checkout Session finished being paid."""

INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
INVOICE_PAYMENT_SUCCEEDED = "invoice.payment_succeeded"
CUSTOMER_SUBSCRIPTION_DELETED = "customer.subscription.deleted"

_LIFECYCLE_STATUS: dict[str, SubscriptionStatus] = {
    INVOICE_PAYMENT_FAILED: SubscriptionStatus.PAST_DUE,
    INVOICE_PAYMENT_SUCCEEDED: SubscriptionStatus.ACTIVE,
    CUSTOMER_SUBSCRIPTION_DELETED: SubscriptionStatus.CANCELED,
}
"""State-machine edges (spec): the recorded status only ever moves on these events."""


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
        return MembershipOut(status=STATUS_FREE, period_end=None, portal_url=None, is_vip=False)
    return MembershipOut(
        status=subscription.status,
        period_end=(
            required_utc(subscription.current_period_end).isoformat()
            if subscription.current_period_end is not None
            else None
        ),
        portal_url=None,
        is_vip=is_vip(subscription),
    )


async def apply_webhook(session: AsyncSession, clock: Clock, event: WebhookEvent) -> None:
    """Advance the subscription state machine with one verified domain event.

    The ``BillingEvent`` unique ``event_id`` is claimed first: losing the conflict means
    Stripe is redelivering an already-processed event, so nothing changes and the caller
    still answers 2xx. Events older than the newest recorded one (out-of-order delivery)
    are audit-only, and event types the state machine does not own never move state.
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
    if await _is_stale(session, event):
        logger.info(
            "billing_event_stale_ignored",
            extra={
                "event": "billing_event_stale_ignored",
                "event_id": event.event_id,
                "event_type": event.type,
                "account_id": event.account_id,
                "outcome": "stale",
            },
        )
        await session.commit()
        return
    applied = await _transition(session, event)
    if applied:
        await session.execute(
            update(BillingEvent).where(BillingEvent.event_id == event.event_id).values(applied=True)
        )
    await session.commit()


async def _is_stale(session: AsyncSession, event: WebhookEvent) -> bool:
    """Out-of-order guard: older-than-newest recorded events never move state (spec 状态机).

    The comparison is per Account over the audit trail, so a replayed historical event
    can only ever append an audit row, never roll the subscription back.
    """
    if not event.account_id:
        return False
    newest = await session.scalar(
        select(func.max(BillingEvent.created)).where(
            BillingEvent.account_id == event.account_id,
            BillingEvent.event_id != event.event_id,
        )
    )
    return newest is not None and event.created < required_utc(newest)


async def _transition(session: AsyncSession, event: WebhookEvent) -> bool:
    """Apply the state change this event type owns; True when state moved.

    ``checkout.session.completed`` creates or reactivates the record (payment success
    takes effect, P2-02); the lifecycle statuses ride the ``_LIFECYCLE_STATUS`` edges:
    invoice failure lands on Past Due, a paid invoice restores Active, a deleted
    subscription is Canceled. A lifecycle event that names an Account without a
    subscription record never invents one - only a checkout mints a record.
    """
    if event.type == CHECKOUT_COMPLETED:
        return await _apply_checkout(session, event)
    return await _apply_lifecycle(session, event)


async def _apply_checkout(session: AsyncSession, event: WebhookEvent) -> bool:
    """Payment success takes effect immediately: mint or reactivate the Account record."""
    if not event.account_id:
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
    _log_membership(event, SubscriptionStatus.ACTIVE.value)
    return True


async def _apply_lifecycle(session: AsyncSession, event: WebhookEvent) -> bool:
    """Advance an existing record along a spec edge; never guess state, never mint one."""
    target = _LIFECYCLE_STATUS.get(event.type)
    if target is None:
        return False
    subscription = await _find_subscription(session, event)
    if subscription is None:
        return False
    changed = False
    if subscription.status != target.value:
        subscription.status = target.value
        changed = True
    if event.current_period_end is not None and (
        subscription.current_period_end is None
        or required_utc(subscription.current_period_end) != event.current_period_end
    ):
        subscription.current_period_end = event.current_period_end
        changed = True
    if event.stripe_subscription_id and subscription.stripe_subscription_id != event.stripe_subscription_id:
        subscription.stripe_subscription_id = event.stripe_subscription_id
        changed = True
    if event.stripe_customer_id and not subscription.stripe_customer_id:
        subscription.stripe_customer_id = event.stripe_customer_id
        changed = True
    if changed:
        _log_membership(event, target.value)
    return changed


async def _find_subscription(session: AsyncSession, event: WebhookEvent) -> Subscription | None:
    """Locate the record an event speaks about: Stripe id first, then Account owner."""
    if event.stripe_subscription_id:
        subscription = await session.scalar(
            select(Subscription).where(
                Subscription.stripe_subscription_id == event.stripe_subscription_id
            )
        )
        if subscription is not None:
            return subscription
    if event.account_id:
        return await session.scalar(
            select(Subscription).where(Subscription.account_id == event.account_id)
        )
    return None


def _log_membership(event: WebhookEvent, status: str) -> None:
    """Structured transition log, traceable to the provider event id (P2-02 whitelist)."""
    logger.info(
        "billing_membership_changed",
        extra={
            "event": "billing_membership_changed",
            "event_id": event.event_id,
            "event_type": event.type,
            "account_id": event.account_id,
            "subscription_status": status,
            "outcome": "applied",
        },
    )
