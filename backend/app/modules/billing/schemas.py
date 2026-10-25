"""Request/response models for the billing module."""

from __future__ import annotations

from pydantic import BaseModel

PORTAL_ENTRY_PATH = "/api/billing/portal"
"""Mounted path of ``POST /billing/portal``: the portal entry ``GET /me/membership``
exposes as ``portal_url``. The managed Stripe link is minted by POSTing here."""


class CheckoutOut(BaseModel):
    """The hosted payment page the browser must be redirected to (full-page nav)."""

    url: str


class PortalOut(BaseModel):
    """The self-service customer portal page (card updates, invoices) for a subscriber."""

    url: str


class MembershipOut(BaseModel):
    """The one subscription truth for the frontend (spec API contract).

    ``status`` is ``"free"`` without a Subscription record, otherwise the recorded
    Stripe status, with the spec's expiry edge applied lazily at read time (an
    expired ``active`` presents as ``canceled``). ``period_end`` is written by the
    webhook state machine and gives the UI what it needs for the Past Due warning
    and the "VIP ends on ..." notice. ``cancel_at_period_end`` marks a *scheduled*
    cancellation: VIP is kept until ``period_end`` and the UI shows the loss
    preview instead of treating the Account as canceled. ``is_vip`` is the
    backend-derived Membership flag (status + period, never stored). ``portal_url``
    is the portal *entry* placeholder required by the P2 contract: the mounted
    path of ``POST /billing/portal``, which mints the managed Stripe link per
    call. The GET never mints a link, so this value is a stable entry point,
    identical across statuses.
    """

    status: str
    period_end: str | None = None
    cancel_at_period_end: bool = False
    is_vip: bool = False
    portal_url: str


class WebhookOut(BaseModel):
    """The webhook acknowledgement. Deliberately opaque: no subscription detail is
    exposed to an unauthenticated caller; Stripe only needs the 2xx to stop retrying."""

    received: bool
