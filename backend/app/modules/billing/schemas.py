"""Request/response models for the billing module."""

from __future__ import annotations

from pydantic import BaseModel


class CheckoutOut(BaseModel):
    """The hosted payment page the browser must be redirected to (full-page nav)."""

    url: str


class MembershipOut(BaseModel):
    """The one subscription truth for the frontend (spec API contract).

    ``status`` is ``"free"`` without an active Subscription record, otherwise the
    recorded Stripe status. ``period_end`` is written by the webhook state machine;
    ``portal_url`` stays a placeholder until the portal ticket (P2-03) lands.
    """

    status: str
    period_end: str | None = None
    portal_url: str | None = None


class WebhookOut(BaseModel):
    """The webhook acknowledgement. Deliberately opaque: no subscription detail is
    exposed to an unauthenticated caller; Stripe only needs the 2xx to stop retrying."""

    received: bool
