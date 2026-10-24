from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterator

from app.errors import AppError, ErrorCode
from app.logging_setup import JsonFormatter, request_id_var
from fastapi import FastAPI
from httpx import AsyncClient


def _record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("app.test", level, __file__, 1, message, None, None)


class _CaptureHandler(logging.Handler):
    """Formats records exactly like production and keeps the parsed JSON lines."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.entries: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))


@contextlib.contextmanager
def _capture_json_logs() -> Iterator[list[dict]]:
    handler = _CaptureHandler()
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield handler.entries
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


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


async def test_failed_request_is_traceable_end_to_end_by_request_id(
    client: AsyncClient, app: FastAPI
) -> None:
    @app.get("/api/test-crash")
    async def crash() -> None:
        raise RuntimeError("boom")

    with _capture_json_logs() as entries:
        response = await client.get("/api/test-crash", headers={"X-Request-ID": "trace-me-42"})

    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == "trace-me-42"

    trace = [entry for entry in entries if entry["request_id"] == "trace-me-42"]
    completed = next(entry for entry in trace if entry["message"] == "request_completed")
    assert completed["level"] == "info"
    assert completed["method"] == "GET"
    assert completed["path"] == "/api/test-crash"
    assert completed["status"] == 500
    assert completed["duration_ms"] >= 0

    failure = next(entry for entry in trace if entry.get("error_code") == "internal_error")
    assert failure["level"] == "error"
    assert "Traceback" in failure["exception"]


async def test_business_error_code_appears_in_the_log_line(
    client: AsyncClient, app: FastAPI
) -> None:
    @app.get("/api/test-reject")
    async def reject() -> None:
        raise AppError(409, ErrorCode.INVALID_REQUEST, "请求与当前状态冲突")

    with _capture_json_logs() as entries:
        response = await client.get("/api/test-reject", headers={"X-Request-ID": "biz-7"})

    assert response.status_code == 409
    trace = [entry for entry in entries if entry["request_id"] == "biz-7"]
    rejection = next(entry for entry in trace if entry["message"] == "app_error")
    assert rejection["error_code"] == "invalid_request"
    completed = next(entry for entry in trace if entry["message"] == "request_completed")
    assert completed["status"] == 409
