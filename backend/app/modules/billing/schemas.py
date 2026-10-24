"""Request/response models for the billing module."""

from __future__ import annotations

from pydantic import BaseModel


class CheckoutOut(BaseModel):
    """The hosted payment page the browser must be redirected to (full-page nav)."""

    url: str


class PortalOut(BaseModel):
    """The self-service customer portal page (card updates, invoices) for a subscriber."""

    url: str


class MembershipOut(BaseModel):
    """The one subscription truth for the frontend (spec API contract).

    ``status`` is ``"free"`` without a Subscription record, otherwise the recorded
    Stripe status. ``period_end`` is written by the webhook state machine and gives
    the UI what it needs for the Past Due warning and the "VIP ends on ..." notice.
    ``is_vip`` is the backend-derived Membership flag (status-based, never stored).
    ``portal_url`` is not a GET field: the managed portal link is minted per call by
    ``POST /billing/portal``.
    """

    status: str
    period_end: str | None = None
    portal_url: str | None = None
    is_vip: bool = False


class WebhookOut(BaseModel):
    """The webhook acknowledgement. Deliberately opaque: no subscription detail is
    exposed to an unauthenticated caller; Stripe only needs the 2xx to stop retrying."""

    received: bool
