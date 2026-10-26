from __future__ import annotations

from typing import Any

from app import db
from app.db import init_db
from app.modules.catalog.models import Subtitle, Video
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker


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


async def test_is_unique_conflict_separates_the_two_identities(
    client: AsyncClient, app: FastAPI
) -> None:
    """The shared classifier reads real SQLite constraint text, per ADR-0001.

    Both concurrent-resolve recoveries lean on this one predicate, so it must tell the
    two UNIQUE identities apart and refuse a foreign-key failure outright.
    """
    await client.get("/health")
    sessionmaker = app.state.sessionmaker

    await _insert(sessionmaker, _video(id="v-1"))
    video_conflict = await _conflict(sessionmaker, _video(id="v-2"))
    await _insert(sessionmaker, _subtitle(video_id="v-1", id="s-1"))
    subtitle_conflict = await _conflict(sessionmaker, _subtitle(video_id="v-1", id="s-2"))
    foreign_key_conflict = await _conflict(sessionmaker, _subtitle(video_id="nope", id="s-3"))

    assert db.is_unique_conflict(
        video_conflict, "videos.platform", "videos.platform_video_id"
    ) is True
    assert db.is_unique_conflict(subtitle_conflict, "subtitles.video_id") is True
    assert db.is_unique_conflict(subtitle_conflict, "videos.platform") is False
    assert db.is_unique_conflict(foreign_key_conflict, "subtitles.video_id") is False


def _video(*, id: str) -> Video:
    return Video(
        id=id,
        platform="youtube",
        platform_video_id="dQw4w9WgXcQ",
        title="标题",
        duration_seconds=1,
        webpage_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )


def _subtitle(*, video_id: str, id: str) -> Subtitle:
    return Subtitle(id=id, video_id=video_id, language="zh-Hans", source_type="manual")


async def _insert(sessionmaker: async_sessionmaker[Any], row: Any) -> None:
    async with sessionmaker() as session:
        session.add(row)
        await session.commit()


async def _conflict(sessionmaker: async_sessionmaker[Any], row: Any) -> IntegrityError:
    """The IntegrityError raised by committing ``row`` against the seeded state."""
    try:
        async with sessionmaker() as session:
            session.add(row)
            await session.commit()
    except IntegrityError as exc:
        return exc
    raise AssertionError(f"expected an IntegrityError from {type(row).__name__}")
