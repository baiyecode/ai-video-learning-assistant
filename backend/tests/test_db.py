from __future__ import annotations

from app.db import init_db
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text


async def test_sqlite_runs_in_wal_mode_with_foreign_keys(client: AsyncClient, app: FastAPI) -> None:
    # The request is only here to start the lifespan (schema creation).
    await client.get("/health")

    async with app.state.sessionmaker() as session:
        journal_mode = (await session.execute(text("PRAGMA journal_mode"))).scalar_one()
        foreign_keys = (await session.execute(text("PRAGMA foreign_keys"))).scalar_one()

    assert str(journal_mode).lower() == "wal"
    assert foreign_keys == 1


async def test_init_db_is_idempotent(client: AsyncClient, app: FastAPI) -> None:
    await client.get("/health")

    await init_db(app.state.engine)
    await init_db(app.state.engine)
