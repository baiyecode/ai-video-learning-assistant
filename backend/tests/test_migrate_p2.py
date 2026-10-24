"""The idempotent accounts migration (ticket #21) against a legacy database.

There is no Alembic: ``init_db`` only creates missing tables, so an existing ``accounts``
table never gains the verification columns without explicit DDL. This exercises the
``scripts.migrate_p2`` seam directly, then boots the real application on the migrated
file to prove a legacy Account logs in and reads as unverified.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
from app.config import Settings
from app.main import create_app
from app.modules.identity.security import hash_password
from asgi_lifespan import LifespanManager
from scripts.migrate_p2 import migrate_accounts

from tests.fakes import make_fake_adapters

PASSWORD = "correct-horse"
LEGACY_COLUMNS = ("id", "email", "password_hash", "created_at")
NEW_COLUMNS = ("email_verified_at", "verification_token_hash", "verification_expires_at")


def _create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE accounts ("
            "id VARCHAR(36) NOT NULL PRIMARY KEY, "
            "email VARCHAR(320) NOT NULL UNIQUE, "
            "password_hash VARCHAR(255) NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        digest = hash_password(PASSWORD)
        connection.execute(
            "INSERT INTO accounts (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("legacy-account-1", "old-timer@example.com", digest, "2026-01-01 00:00:00"),
        )
        connection.commit()
    finally:
        connection.close()


def _columns(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[1] for row in connection.execute("PRAGMA table_info(accounts)")]
    finally:
        connection.close()


def test_migrate_accounts_adds_missing_verification_columns_once(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    _create_legacy_database(database)

    added = migrate_accounts(database)
    assert sorted(added) == sorted(NEW_COLUMNS)
    assert sorted(_columns(database)) == sorted(LEGACY_COLUMNS + NEW_COLUMNS)

    # Idempotent: a second run changes nothing, and a database without the table
    # at all is left to ``init_db`` (which creates the full schema).
    assert migrate_accounts(database) == []
    assert migrate_accounts(tmp_path / "brand-new-empty.db") == []


async def test_legacy_account_logs_in_and_stays_unverified_after_migration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "app.db"
    _create_legacy_database(database)
    migrate_accounts(database)

    settings = Settings(
        _env_file=None,
        env="test",
        secret_key="test-only-secret",
        database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
        data_dir=tmp_path / "data",
        log_level="WARNING",
    )
    app = create_app(settings=settings, adapters=make_fake_adapters())

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            login = await client.post(
                "/api/auth/login", json={"email": "old-timer@example.com", "password": PASSWORD}
            )
            assert login.status_code == 200, login.text

            me = await client.get(
                "/api/me",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            )
            assert me.status_code == 200, me.text
            assert me.json()["account"]["email_verified_at"] is None
