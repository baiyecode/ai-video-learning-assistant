from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from tests.fakes import make_fake_adapters


@pytest.fixture(autouse=True)
def _never_talk_to_sentry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never initialise a real Sentry client, even on a developer machine."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSRF checks resolve allowed hosts; tests must never hit real DNS.

    A test may override this with its own ``monkeypatch`` (on the resolver function
    or on ``socket.getaddrinfo``) to exercise private-address rejection.
    """
    monkeypatch.setattr(
        "app.modules.catalog.urls.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ],
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: isolated SQLite file, no env file, no external services."""
    return Settings(
        _env_file=None,
        env="test",
        secret_key="test-only-secret",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        data_dir=tmp_path / "data",
        log_level="WARNING",
    )


@pytest.fixture
def adapters() -> Adapters:
    return make_fake_adapters()


@pytest.fixture
def app(settings: Settings, adapters: Adapters) -> FastAPI:
    return create_app(settings=settings, adapters=adapters)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """In-process HTTP client: no server, no sockets, but full lifespan."""
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client
