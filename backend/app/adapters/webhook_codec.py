"""Stripe-style webhook signature verification and event decoding (pure stdlib).

Shared by every ``BillingGateway`` adapter (production Stripe, demo, test fake) so
the wire contract lives in exactly one place. The scheme mirrors Stripe's published
``Stripe-Signature`` header: ``t=<unix>,v1=<hex hmac>``, where the HMAC is
SHA-256 over ``"<t>." + raw body`` keyed by the webhook secret. Verification is
constant-time; a timestamp-tolerance check is deliberately absent (spec: replayed
events are neutralised by the ``BillingEvent`` idempotency gate, not the timestamp).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from ..errors import AppError, ErrorCode
from ..ports import WebhookEvent

_MESSAGE_SIGNATURE_INVALID = "webhook 签名校验失败"
_MESSAGE_EVENT_UNREADABLE = "webhook 事件载荷无法解析"

_HASH = hashlib.sha256


def compute_signature(secret: str, timestamp: int, payload: bytes) -> str:
    """The ``v1`` HMAC a provider would send for this (timestamp, body) pair."""
    signed = f"{timestamp}.".encode() + payload
    return hmac.new(secret.encode(), signed, _HASH).hexdigest()


def sign_header(secret: str, timestamp: int, payload: bytes) -> str:
    """A complete ``Stripe-Signature`` header value for the given body."""
    return f"t={timestamp},v1={compute_signature(secret, timestamp, payload)}"


def verify_and_decode(*, payload: bytes, signature_header: str, secret: str) -> WebhookEvent:
    """Verify the signature then decode the body into one domain event.

    Any verification or decoding failure raises ``AppError`` 400; the caller must
    treat the payload as untrusted until this returns.
    """
    timestamp, candidates = _parse_header(signature_header)
    expected = compute_signature(secret, timestamp, payload)
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise AppError(400, ErrorCode.INVALID_SIGNATURE, _MESSAGE_SIGNATURE_INVALID)
    return _decode_event(payload)


def _parse_header(signature_header: str) -> tuple[int, list[str]]:
    timestamp: int | None = None
    candidates: list[str] = []
    for part in signature_header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif name == "v1" and value:
            candidates.append(value)
    if timestamp is None or not candidates:
        raise AppError(400, ErrorCode.INVALID_SIGNATURE, _MESSAGE_SIGNATURE_INVALID)
    return timestamp, candidates


def _decode_event(payload: bytes) -> WebhookEvent:
    try:
        document: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AppError(400, ErrorCode.INVALID_REQUEST, _MESSAGE_EVENT_UNREADABLE) from exc
    event_id = document.get("id")
    event_type = document.get("type")
    created = document.get("created")
    if not isinstance(event_id, str) or not isinstance(event_type, str) or not isinstance(created, int):
        raise AppError(400, ErrorCode.INVALID_REQUEST, _MESSAGE_EVENT_UNREADABLE)
    obj = document.get("data", {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    raw_status = obj.get("status")
    raw_cancel = obj.get("cancel_at_period_end")
    return WebhookEvent(
        event_id=event_id,
        type=event_type,
        created=datetime.fromtimestamp(created, tz=UTC),
        account_id=obj.get("client_reference_id") or metadata.get("account_id"),
        provider_customer_id=obj.get("customer"),
        provider_subscription_id=obj.get("subscription"),
        current_period_end=_epoch_to_utc(obj.get("current_period_end")),
        price_id=metadata.get("price_id"),
        subscription_status=raw_status if isinstance(raw_status, str) else None,
        cancel_at_period_end=raw_cancel if isinstance(raw_cancel, bool) else None,
    )


def _epoch_to_utc(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)
