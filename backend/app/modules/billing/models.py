"""SQLAlchemy models for billing: the Subscription record behind VIP Membership.

VIP Membership is a derived state: ``status`` in ``VIP_STATUSES`` and nothing else.
The Account never stores a flag (GLOSSARY: _Avoid_ ``is_vip``). Stripe IDs are the
idempotency keys the future webhook handler upserts against; ``account_id`` is
unique because one Account holds at most one subscription.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price_id: Mapped[str] = mapped_column(String(64), nullable=False)


def is_vip(subscription: Subscription | None) -> bool:
    """The single VIP truth: derived from the subscription status, never stored."""
    return subscription is not None and subscription.status in VIP_STATUSES
