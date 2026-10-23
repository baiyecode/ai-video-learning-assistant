from __future__ import annotations

from app.errors import AppError
from fastapi import FastAPI
from httpx import AsyncClient


async def test_unhandled_exception_becomes_internal_error_without_stack_trace(
    client: AsyncClient, app: FastAPI
) -> None:
    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals exploded at line 42")

    response = await client.get("/api/_test/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["details"] == {}
    assert body["error"]["request_id"]
    assert response.headers["x-request-id"] == body["error"]["request_id"]
    raw = response.text
    assert "secret internals" not in raw
    assert "Traceback" not in raw
    assert "RuntimeError" not in raw


async def test_app_error_is_serialised_with_code_message_and_details(
    client: AsyncClient, app: FastAPI
) -> None:
    @app.get("/api/_test/quota")
    async def quota() -> None:
        raise AppError(
            status=429,
            code="quota_exhausted",
            message="今日分析次数已用完",
            details={"remaining": 0},
        )

    response = await client.get("/api/_test/quota")

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "quota_exhausted"
    assert body["error"]["message"] == "今日分析次数已用完"
    assert body["error"]["details"] == {"remaining": 0}
    assert body["error"]["request_id"] == response.headers["x-request-id"]


async def test_unknown_route_uses_the_unified_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/nope")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["details"] == {}
    assert body["error"]["request_id"] == response.headers["x-request-id"]
