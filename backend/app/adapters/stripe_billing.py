"""Stripe billing gateway adapter (tickets P2-01 / P2-02).

Wraps the Stripe SDK behind the ``BillingGateway`` port. Constructing this adapter
always succeeds, even without credentials: the SDK import and every network call are
deferred, and a request made while ``APP_STRIPE_API_KEY``/``APP_STRIPE_PRICE_ID`` are
missing answers an understandable 503 instead of crashing at import or startup.

Webhook verification needs no SDK: the ``Stripe-Signature`` HMAC scheme is implemented
in stdlib by ``app.adapters.webhook_codec``, so the gateway can vet and decode events
even while the account-level SDK calls are unavailable.
"""

from __future__ import annotations

import asyncio
import logging

from app.adapters.webhook_codec import verify_and_decode
from app.config import Settings
from app.errors import AppError, ErrorCode
from app.ports import CheckoutSession, CustomerPortal, WebhookEvent

logger = logging.getLogger("app.adapters.stripe_billing")

_MESSAGE_BILLING_NOT_CONFIGURED = "订阅支付服务尚未配置，暂时无法升级"
_MESSAGE_BILLING_UNAVAILABLE = "订阅支付服务暂时不可用，请稍后重试"


class StripeBillingGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _require_config(self) -> None:
        if not (self._settings.stripe_api_key.strip() and self._settings.stripe_price_id.strip()):
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_BILLING_NOT_CONFIGURED)

    async def create_checkout(
        self,
        *,
        account_id: str,
        email: str | None,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        self._require_config()

        def _create() -> dict:
            # Deferred inside the worker: the SDK import itself must not crash or leak
            # as a 500 when the package is missing (deployment forgot ``uv add stripe``).
            import stripe

            stripe.api_key = self._settings.stripe_api_key
            params: dict = {
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "client_reference_id": account_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "allow_promotion_codes": False,
                "metadata": {"account_id": account_id},
            }
            if email:
                params["customer_email"] = email
            return stripe.checkout.Session.create(**params)

        try:
            session = await asyncio.to_thread(_create)
        except AppError:
            raise
        except Exception as exc:
            # Never leak SDK details or a 500 stack: the payment provider is simply down.
            logger.warning(
                "stripe_checkout_failed", extra={"event": "stripe_checkout_failed"}, exc_info=exc
            )
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_BILLING_UNAVAILABLE) from exc
        return CheckoutSession(id=str(session["id"]), url=str(session["url"]))

    async def create_portal(self, *, provider_customer_id: str, return_url: str) -> CustomerPortal:
        """Mint a Stripe customer-portal session for the subscription owner.

        Same deferred-SDK shape as checkout: no credentials means a clear 503, and an
        empty customer id (webhooks never carried one) cannot open a portal either.
        """
        self._require_config()
        if not provider_customer_id.strip():
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_BILLING_UNAVAILABLE)

        def _create() -> dict:
            import stripe

            stripe.api_key = self._settings.stripe_api_key
            return stripe.billing_portal.Session.create(
                customer=provider_customer_id, return_url=return_url
            )

        try:
            session = await asyncio.to_thread(_create)
        except AppError:
            raise
        except Exception as exc:
            logger.warning(
                "stripe_portal_failed", extra={"event": "stripe_portal_failed"}, exc_info=exc
            )
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_BILLING_UNAVAILABLE) from exc
        return CustomerPortal(url=str(session["url"]))

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        """Verify and decode a Stripe webhook. Without ``APP_STRIPE_WEBHOOK_SECRET``
        there is no key to check against, so the gateway reports itself unavailable."""
        secret = self._settings.stripe_webhook_secret.strip()
        if not secret:
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_BILLING_NOT_CONFIGURED)
        return verify_and_decode(payload=payload, signature_header=signature, secret=secret)
