"""Billing domain logic: the upgrade entry point, the membership read and the webhook state machine.

State policy (spec): the subscription record is only advanced by gateway webhooks,
never guessed elsewhere. Creating a checkout therefore stores nothing - it just asks the
port for a hosted payment page - and membership is a pure read of the record. The one
exception is the spec's expiry edge (``current_period_end`` 过期 → canceled): the read
side derives it lazily against the injected Clock without rewriting the row, so state
stays webhook-driven while no expired VIP is ever granted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.modules.billing.models import (
    VIP_STATUSES,
    BillingEvent,
    Subscription,
    SubscriptionStatus,
    new_id,
)
from app.modules.billing.schemas import (
    PORTAL_ENTRY_PATH,
    CheckoutOut,
    MembershipOut,
    PortalOut,
)
from app.modules.identity.models import Account
from app.ports import BillingGateway, Clock, WebhookEvent
from app.timeutil import required_utc

logger = logging.getLogger("app.modules.billing")

_MESSAGE_NO_SUBSCRIPTION = "还没有可管理的订阅，请先完成升级支付"

STATUS_FREE = "free"
"""Membership status for an Account with no subscription record."""

CHECKOUT_COMPLETED = "checkout.session.completed"
"""The event that grants a membership: the Checkout Session finished being paid."""

INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
INVOICE_PAYMENT_SUCCEEDED = "invoice.payment_succeeded"
CUSTOMER_SUBSCRIPTION_DELETED = "customer.subscription.deleted"
SUBSCRIPTION_CREATED = "customer.subscription.created"
SUBSCRIPTION_UPDATED = "customer.subscription.updated"

_LIFECYCLE_STATUS: dict[str, SubscriptionStatus] = {
    INVOICE_PAYMENT_FAILED: SubscriptionStatus.PAST_DUE,
    INVOICE_PAYMENT_SUCCEEDED: SubscriptionStatus.ACTIVE,
    CUSTOMER_SUBSCRIPTION_DELETED: SubscriptionStatus.CANCELED,
}
"""State-machine edges (spec): the recorded status only ever moves on these events."""

_PROVIDER_SUBSCRIPTION_STATUS: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.TRIAL_ENDING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
}
"""Translation of the provider's subscription-object status. Unlisted statuses (and
``created``/``updated`` events without one) never move state - the local record keeps
the last status an event of authority wrote."""


@dataclass(frozen=True, slots=True)
class MembershipState:
    """The one derived membership truth for one Account at one instant.

    ``status`` and ``vip_active`` already honour the lazy expiry edge: an ``active`` /
    ``trial_ending`` record past ``current_period_end`` presents as ``canceled`` /
    non-VIP (spec Story 10) without the row being rewritten. ``cancel_at_period_end``
    is the provider's *scheduled* cancellation: VIP is retained until ``period_end``
    and the UI turns that pair into the 「VIP 保留至 X」 preview.
    """

    status: str
    vip_active: bool
    period_end: datetime | None
    cancel_at_period_end: bool


def _period_end(subscription: Subscription) -> datetime | None:
    return (
        required_utc(subscription.current_period_end)
        if subscription.current_period_end is not None
        else None
    )


def _past_period_end(subscription: Subscription, now: datetime) -> bool:
    """The spec's 过期 edge evaluated at read time; unknown end dates never expire."""
    if subscription.status not in VIP_STATUSES:
        return False
    period_end = _period_end(subscription)
    return period_end is not None and period_end <= now


async def membership_state(
    session: AsyncSession, account_id: str, *, now: datetime
) -> MembershipState:
    """The single subscription read for the whole application (billing and Analysis).

    Other modules must read membership through this function, never by selecting
    ``Subscription`` themselves: the status/flag derivation (including the lazy
    expiry edge) then lives in exactly one place.
    """
    subscription = await session.scalar(
        select(Subscription).where(Subscription.account_id == account_id)
    )
    if subscription is None:
        return MembershipState(
            status=STATUS_FREE, vip_active=False, period_end=None, cancel_at_period_end=False
        )
    expired = _past_period_end(subscription, now)
    return MembershipState(
        status=SubscriptionStatus.CANCELED.value if expired else subscription.status,
        vip_active=not expired and subscription.status in VIP_STATUSES,
        period_end=_period_end(subscription),
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


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


async def open_portal(
    session: AsyncSession,
    gateway: BillingGateway,
    account: Account,
    *,
    origin: str,
) -> PortalOut:
    """Mint the provider-hosted self-service link (card updates, invoices) for a subscriber.

    The subscription record is the gate: without one there is nothing to manage, and
    the caller gets an understood 404 instead of a provider round trip. Past Due and
    Canceled records keep the door open - those are exactly the states where users
    must fix payment details or read billing history.
    """
    subscription = await session.scalar(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    if subscription is None:
        raise AppError(404, ErrorCode.SUBSCRIPTION_NOT_FOUND, _MESSAGE_NO_SUBSCRIPTION)
    portal = await gateway.create_portal(
        provider_customer_id=subscription.provider_customer_id or "",
        return_url=f"{origin}/?portal=finished",
    )
    return PortalOut(url=portal.url)


async def membership(
    session: AsyncSession, account_id: str, settings: Settings, *, now: datetime
) -> MembershipOut:
    """The Account's subscription truth: the derived read, never a recomputing write.

    ``portal_url`` is the spec's portal *entry* placeholder (issue #17 AC): the
    mounted POST path, identical for every status because the managed Stripe link
    is only ever minted by that POST, never by this read.

    The displayed price and the free Quota ride along from ``settings`` (ticket #41
    follow-up): they are the values the server enforces, so the UI has a runtime source
    for them and ``APP_SUBSCRIPTION_MONTHLY_USD`` is no longer read only by its own test.
    """
    state = await membership_state(session, account_id, now=now)
    return MembershipOut(
        status=state.status,
        period_end=state.period_end.isoformat() if state.period_end is not None else None,
        cancel_at_period_end=state.cancel_at_period_end,
        vip_active=state.vip_active,
        portal_url=PORTAL_ENTRY_PATH,
        monthly_price_usd=settings.subscription_monthly_usd,
        daily_free_analysis_limit=settings.analysis_daily_quota,
    )


async def apply_webhook(session: AsyncSession, clock: Clock, event: WebhookEvent) -> None:
    """Advance the subscription state machine with one verified domain event.

    The ``BillingEvent`` unique ``event_id`` is claimed first: losing the conflict means
    Stripe is redelivering an already-processed event, so nothing changes and the caller
    still answers 2xx. Events older than the newest recorded one (out-of-order delivery)
    are audit-only, and event types the state machine does not own never move state.
    """
    account_id = await _effective_account_id(session, event)
    claim = await session.execute(
        sqlite_insert(BillingEvent)
        .values(
            id=new_id(),
            event_id=event.event_id,
            type=event.type,
            created=event.created,
            processed_at=clock.now(),
            account_id=account_id,
            provider_subscription_id=event.provider_subscription_id,
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
    if await _is_stale(session, event, account_id):
        logger.info(
            "billing_event_stale_ignored",
            extra={
                "event": "billing_event_stale_ignored",
                "event_id": event.event_id,
                "event_type": event.type,
                "account_id": account_id,
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


async def _effective_account_id(session: AsyncSession, event: WebhookEvent) -> str | None:
    """The Account an event belongs to.

    Real invoice/subscription events name only Stripe ids; the local owner is resolved
    through the subscription record so the audit trail and the out-of-order guard stay
    per Account. Unmatched events keep ``None`` - nothing is invented.
    """
    if event.account_id:
        return event.account_id
    if event.provider_subscription_id:
        return await session.scalar(
            select(Subscription.account_id).where(
                Subscription.provider_subscription_id == event.provider_subscription_id
            )
        )
    return None


async def _is_stale(
    session: AsyncSession, event: WebhookEvent, account_id: str | None
) -> bool:
    """Out-of-order guard: older-than-newest recorded events never move state (spec 状态机).

    The comparison is per Account over the audit trail, so a replayed historical event
    can only ever append an audit row, never roll the subscription back.
    """
    if not account_id:
        return False
    newest = await session.scalar(
        select(func.max(BillingEvent.created)).where(
            BillingEvent.account_id == account_id,
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
            provider_customer_id=event.provider_customer_id,
            provider_subscription_id=_checkout_subscription_key(event),
            status=SubscriptionStatus.ACTIVE.value,
            current_period_end=event.current_period_end,
            # A fresh payment cancels any previously scheduled period-end cancellation.
            cancel_at_period_end=False,
            price_id=event.price_id or "",
        )
        session.add(subscription)
    else:
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.current_period_end = event.current_period_end
        subscription.cancel_at_period_end = False
        if event.provider_subscription_id:
            subscription.provider_subscription_id = event.provider_subscription_id
        if event.provider_customer_id:
            subscription.provider_customer_id = event.provider_customer_id
        if event.price_id:
            subscription.price_id = event.price_id
    _log_membership(event, SubscriptionStatus.ACTIVE.value)
    return True


def _checkout_subscription_key(event: WebhookEvent) -> str:
    """The Stripe subscription id, or a provisional unique key when the object lacks one.

    ``provider_subscription_id`` is NOT NULL/unique (the webhook upsert key), but a
    checkout object may arrive before the provider created the subscription. The
    event id then parks the row under a key that can never collide with a provider
    id; the first ``customer.subscription.*`` event naming the real id rewrites it
    (:func:`_apply_lifecycle` backfills), exactly like the period-end backfill.
    """
    return event.provider_subscription_id or event.event_id


async def _apply_lifecycle(session: AsyncSession, event: WebhookEvent) -> bool:
    """Advance an existing record along a spec edge; never guess state, never mint one."""
    object_event = event.type in (SUBSCRIPTION_CREATED, SUBSCRIPTION_UPDATED)
    if event.type not in _LIFECYCLE_STATUS and not object_event:
        return False
    target = _LIFECYCLE_STATUS.get(event.type)
    if target is None and object_event:
        target = _PROVIDER_SUBSCRIPTION_STATUS.get(event.subscription_status or "")
    subscription = await _find_subscription(session, event)
    if subscription is None:
        return False
    changed = False
    if target is not None and subscription.status != target.value:
        subscription.status = target.value
        changed = True
    if (
        object_event
        and event.cancel_at_period_end is not None
        and subscription.cancel_at_period_end != event.cancel_at_period_end
    ):
        subscription.cancel_at_period_end = event.cancel_at_period_end
        changed = True
    if event.current_period_end is not None and (
        subscription.current_period_end is None
        or required_utc(subscription.current_period_end) != event.current_period_end
    ):
        subscription.current_period_end = event.current_period_end
        changed = True
    if (
        event.provider_subscription_id
        and subscription.provider_subscription_id != event.provider_subscription_id
    ):
        subscription.provider_subscription_id = event.provider_subscription_id
        changed = True
    if event.provider_customer_id and not subscription.provider_customer_id:
        subscription.provider_customer_id = event.provider_customer_id
        changed = True
    if changed:
        _log_membership(event, subscription.status)
    return changed


async def _find_subscription(session: AsyncSession, event: WebhookEvent) -> Subscription | None:
    """Locate the record an event speaks about: Stripe id first, then Account owner."""
    if event.provider_subscription_id:
        subscription = await session.scalar(
            select(Subscription).where(
                Subscription.provider_subscription_id == event.provider_subscription_id
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
