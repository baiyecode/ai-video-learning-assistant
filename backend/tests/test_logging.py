from __future__ import annotations

import json
import logging

from app.logging_setup import JsonFormatter, request_id_var


def _record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("app.test", level, __file__, 1, message, None, None)


def test_json_formatter_emits_a_single_json_object() -> None:
    payload = json.loads(JsonFormatter().format(_record("hello")))

    assert payload["message"] == "hello"
    assert payload["level"] == "info"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] is None


def test_json_formatter_includes_request_id_from_context() -> None:
    token = request_id_var.set("req-123")
    try:
        payload = json.loads(JsonFormatter().format(_record("with id")))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "req-123"


def test_json_formatter_never_raises_on_exception_records() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))

    assert "Traceback" in payload["exception"]
    assert "boom" in payload["exception"]
