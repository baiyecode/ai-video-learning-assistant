"""Request/response models for the billing module."""

from __future__ import annotations

from pydantic import BaseModel


class CheckoutOut(BaseModel):
    """The hosted payment page the browser must be redirected to (full-page nav)."""

    url: str
