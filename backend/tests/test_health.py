from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def test_health_reports_service_database_disk_and_process_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ai-video-learning-assistant"
    assert body["version"]
    assert set(body["checks"]) == {"database", "disk", "process"}
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["database"]["journal_mode"] == "wal"
    assert body["checks"]["disk"]["ok"] is True
    assert body["checks"]["disk"]["writable"] is True
    assert body["checks"]["process"]["ok"] is True
    assert body["checks"]["process"]["pid"] > 0


async def test_health_returns_503_when_database_is_unavailable(
    client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    missing_dir = tmp_path / "does-not-exist"
    broken_engine = create_async_engine(
        f"sqlite+aiosqlite:///{(missing_dir / 'broken.db').as_posix()}"
    )
    app.state.sessionmaker = async_sessionmaker(broken_engine, expire_on_commit=False)
    try:
        response = await client.get("/health")
    finally:
        await broken_engine.dispose()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] is False
    assert body["checks"]["database"]["error"]
    assert body["checks"]["disk"]["ok"] is True


async def test_health_returns_503_when_media_directory_is_not_writable(
    client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    # A regular file in place of a directory: creating ``<file>/media`` always fails,
    # which is how a read-only or missing mount looks to the health check.
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    app.state.settings.data_dir = blocker
    try:
        response = await client.get("/health")
    finally:
        app.state.settings.data_dir = tmp_path / "data"

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["disk"]["ok"] is False
    assert body["checks"]["disk"]["error"]
    assert body["checks"]["database"]["ok"] is True


@pytest.mark.parametrize("path", ["/health", "/api/missing"])
async def test_every_response_carries_a_request_id(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.headers.get("x-request-id")


async def test_inbound_request_id_is_preserved(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


class _Value:
    def __init__(self, value: str) -> None:
        self._value = value

    def scalar_one(self) -> str:
        return self._value


class _FlakySession:
    def __init__(self, factory: _FlakySessionmaker) -> None:
        self._factory = factory

    async def __aenter__(self) -> _FlakySession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> _Value:
        if self._factory.locked_attempts > 0:
            self._factory.locked_attempts -= 1
            from sqlalchemy.exc import OperationalError

            raise OperationalError("PRAGMA", {}, Exception("database is locked"))
        text = str(statement)
        return _Value("ok" if "quick_check" in text else "wal")

    async def rollback(self) -> None:
        return None


class _FlakySessionmaker:
    def __init__(self, locked_attempts: int) -> None:
        self.locked_attempts = locked_attempts
        self.calls = 0

    def __call__(self) -> _FlakySession:
        self.calls += 1
        return _FlakySession(self)


async def test_health_retries_a_transient_writer_lock() -> None:
    from app.modules.ops import health

    factory = _FlakySessionmaker(locked_attempts=2)

    result = await health.check_database(factory)  # type: ignore[arg-type]

    assert result["ok"] is True
    assert result["writable"] is True
    assert factory.calls == 3


async def test_health_reports_a_lock_that_never_clears() -> None:
    from app.modules.ops import health

    factory = _FlakySessionmaker(locked_attempts=99)

    result = await health.check_database(factory)  # type: ignore[arg-type]

    assert result["ok"] is False
    assert result["error"] == "database_check_failed"
    assert factory.calls == 3
