"""Async SQLAlchemy 2 setup for SQLite (WAL) and schema creation."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import Settings

logger = logging.getLogger("app.db")


def is_unique_conflict(exc: IntegrityError, *columns: str) -> bool:
    """Whether ``exc`` is a UNIQUE violation naming all of these ``table.column`` items.

    SQLite is the only supported engine (ADR-0001) and its UNIQUE error text lists the
    offending columns (``UNIQUE constraint failed: subtitles.video_id``), so the column
    list is what separates the concurrent insert a caller may adopt from any other
    constraint violation - the latter is a bug and must surface, not be swallowed.
    """
    if getattr(exc.orig, "sqlite_errorname", "") != "SQLITE_CONSTRAINT_UNIQUE":
        return False
    message = str(getattr(exc, "orig", exc)).lower()
    return all(column.lower() in message for column in columns)


class Base(DeclarativeBase):
    """Declarative base shared by every module's models."""


def _apply_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_engine_and_sessionmaker(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)
    if engine.url.get_backend_name() == "sqlite":
        event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, sessionmaker


async def init_db(engine: AsyncEngine) -> None:
    """Create any missing tables. Safe to call more than once."""
    # Importing the registry attaches every module's models to Base.metadata.
    from . import models_registry  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info(
        "database_initialised",
        extra={"event": "database_initialised", "tables": len(Base.metadata.tables)},
    )
