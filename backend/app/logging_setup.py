"""JSON logging and per-request correlation ids."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Anything longer or with control characters is not treated as a trusted correlation id.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

_EXTRA_FIELDS = (
    "event",
    "code",
    "error_code",
    "method",
    "path",
    "duration_ms",
    "env",
)


class JsonFormatter(logging.Formatter):
    """One JSON object per log line; stable keys for log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get() or None,
        }
        status = getattr(record, "status", None)
        if status is None:
            status = getattr(record, "status_code", None)
        if status is not None:
            payload["status"] = status
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        # Error handlers pass ``code``; the log contract calls the stable code ``error_code``.
        if "error_code" not in payload and payload.get("code") is not None:
            payload["error_code"] = payload.pop("code")
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_JSON_HANDLER_MARKER = "_is_app_json_handler"


def configure_logging(level: str = "INFO") -> None:
    """Install a JSON handler on the root logger. Idempotent across app factories."""
    resolved = logging.getLevelName(level.upper())
    if not isinstance(resolved, int):
        resolved = logging.INFO

    root = logging.getLogger()
    root.setLevel(resolved)

    json_handlers = [h for h in root.handlers if getattr(h, _JSON_HANDLER_MARKER, False)]
    if not json_handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        setattr(handler, _JSON_HANDLER_MARKER, True)
        root.addHandler(handler)
    for handler in json_handlers:
        handler.setLevel(resolved)


logger = logging.getLogger("app.request")


class RequestContextMiddleware:
    """Assigns a request id, exposes it via contextvar/``request.state`` and echoes it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        status_code = 500
        started = time.perf_counter()
        failed = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Keep the contextvar set: Starlette's outer ServerErrorMiddleware logs and
            # hands off to Sentry after this middleware returns, and both need the id.
            failed = True
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            level = logging.DEBUG if scope.get("path") == "/health" else logging.INFO
            logger.log(
                level,
                "request_completed",
                extra={
                    "event": "request_completed",
                    "status": status_code,
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "duration_ms": duration_ms,
                },
            )
            if not failed:
                request_id_var.reset(token)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-request-id":
            decoded = value.decode("latin-1")
            return decoded if _SAFE_REQUEST_ID.match(decoded) else None
    return None
