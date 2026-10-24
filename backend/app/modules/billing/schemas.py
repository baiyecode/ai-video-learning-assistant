"""Request/response models for the billing module."""

from __future__ import annotations

from pydantic import BaseModel


class CheckoutOut(BaseModel):
    """The hosted payment page the browser must be redirected to (full-page nav)."""

    url: str


class MembershipOut(BaseModel):
    """The one subscription truth for the frontend (spec API contract).

    ``status`` is ``"free"`` without an active Subscription record, otherwise the
    recorded Stripe status. ``period_end``/``portal_url`` are placeholders until the
    webhook/portal tickets fill them in.
    """

    status: str
    period_end: str | None = None
    portal_url: str | None = None
