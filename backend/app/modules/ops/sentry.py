"""Optional Sentry integration.

Initialised only when ``SENTRY_DSN`` is set; otherwise every call is a no-op and the
application has no Sentry dependency at runtime. Unhandled exceptions are captured by
Sentry's default logging integration (the unified error handler logs them at ERROR with
``exc_info``), and every event is tagged with the current ``request_id``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app import __version__
from app.logging_setup import request_id_var

logger = logging.getLogger("app.ops.sentry")

_RELEASE = f"ai-video-learning-assistant@{__version__}"


def tag_request_id(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """``before_send`` hook: attach the request id that was active when the error happened."""
    request_id = request_id_var.get()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def init_sentry(
    *,
    dsn: str | None = None,
    environment: str = "development",
    traces_sample_rate: float | None = None,
) -> bool:
    """Initialise Sentry when a DSN is available. Returns ``True`` only if it was enabled."""
    resolved = (dsn if dsn is not None else os.getenv("SENTRY_DSN", "")).strip()
    if not resolved:
        return False

    if traces_sample_rate is None:
        try:
            traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0"))
        except ValueError:
            traces_sample_rate = 0.0

    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - sentry-sdk is a regular dependency
        logger.warning("sentry_sdk_not_installed", extra={"event": "sentry_sdk_not_installed"})
        return False

    try:
        sentry_sdk.init(
            dsn=resolved,
            environment=environment,
            release=_RELEASE,
            traces_sample_rate=traces_sample_rate,
            send_default_pii=False,
            before_send=tag_request_id,
        )
    except Exception:  # noqa: BLE001 - observability must never prevent the app from starting
        logger.warning("sentry_init_failed", exc_info=True, extra={"event": "sentry_init_failed"})
        return False

    logger.info("sentry_initialised", extra={"event": "sentry_initialised", "env": environment})
    return True
