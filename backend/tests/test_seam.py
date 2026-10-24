from __future__ import annotations

from app.container import Adapters
from fastapi import FastAPI
from httpx import AsyncClient


async def test_in_process_asgi_call_with_injected_fakes(
    client: AsyncClient, app: FastAPI, adapters: Adapters
) -> None:
    """The whole app is exercised over ASGI: no sockets, no real adapters."""
    assert app.state.adapters is adapters
    assert app.state.settings.env == "test"
    assert app.state.sessionmaker is not None

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_module_level_asgi_app_exists_for_uvicorn() -> None:
    from app.main import app as asgi_app

    assert isinstance(asgi_app, FastAPI)
    assert asgi_app.version
