"""SQLAlchemy models for billing: Subscription records and the webhook audit trail.

VIP Membership is a derived state: ``status`` in ``VIP_STATUSES`` with the paid period
not yet elapsed, and nothing else. The Account never stores a flag (GLOSSARY: _Avoid_
``is_vip``). Provider subscription IDs are the idempotency keys the webhook handler
upserts against (the physical columns keep the ``stripe_*`` names from the spec's
data model); ``account_id`` is unique because one Account holds at most one
subscription.
``cancel_at_period_end`` mirrors the provider's *scheduled* cancellation: VIP is kept
until ``current_period_end``, and the read side turns that into the UI preview.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    """The one id generator shared by this module's models and the webhook writer."""
    return str(uuid4())


class SubscriptionStatus(StrEnum):
    """Lifecycle states mirrored from Stripe (spec P2 state machine)."""

    ACTIVE = "active"
    TRIAL_ENDING = "trial_ending"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


VIP_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL_ENDING})
"""Statuses that grant VIP Membership; cancellations stay VIP until period end."""


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    provider_customer_id: Mapped[str | None] = mapped_column(
        "stripe_customer_id", String(64), nullable=True
    )
    provider_subscription_id: Mapped[str] = mapped_column(
        "stripe_subscription_id", String(64), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_id: Mapped[str] = mapped_column(String(64), nullable=False)


class BillingEvent(Base):
    """Append-only audit trail of every signature-verified webhook event.

    The unique ``event_id`` doubles as the idempotency gate: a redelivery loses the
    ``INSERT ... ON CONFLICT DO NOTHING`` and is therefore never applied twice.
    ``account_id`` is a plain string, not a FK: billing disputes outlive account
    deletion, and events whose Account cannot be resolved must still be recorded.
    """

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        "stripe_subscription_id", String(64), nullable=True
    )
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
