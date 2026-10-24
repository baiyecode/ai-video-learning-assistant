"""Idempotent DDL migration for the P2 email-verification columns on ``accounts``.

There is no Alembic in this project (ADR-0001): ``init_db`` only creates *missing
tables*, so an existing ``accounts`` table never gains new columns by itself. Run
this once against a pre-P2 database after deploying ticket #21; fresh databases
need nothing (``init_db`` already creates the full schema).

Usage (inside the api image or any environment with the backend dependencies)::

    APP_DATABASE_URL=sqlite+aiosqlite:////data/app.db python -m scripts.migrate_p2

Legacy rows keep ``email_verified_at = NULL``: they are unverified by construction
and are never bulk-marked as verified.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings

from scripts.backup import database_path_from_url

# Column name -> SQLite column type, in declaration order.
_VERIFICATION_COLUMNS: dict[str, str] = {
    "email_verified_at": "DATETIME",
    "verification_token_hash": "VARCHAR(64)",
    "verification_expires_at": "DATETIME",
}

# Scheduled-cancellation flag on subscriptions (ticket #20, story 8 preview).
_SUBSCRIPTION_COLUMNS: dict[str, str] = {
    "cancel_at_period_end": "BOOLEAN NOT NULL DEFAULT 0",
}


def _add_missing_columns(
    connection: sqlite3.Connection, table: str, columns: dict[str, str]
) -> list[str]:
    """ALTER the missing columns of ``columns`` onto ``table``; return their names."""
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if table not in tables:
        return []
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    added: list[str] = []
    for name, column_type in columns.items():
        if name in existing:
            continue
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
        added.append(name)
    return added


def migrate_accounts(database_path: Path) -> list[str]:
    """Add missing verification columns to ``accounts``; return the columns added.

    Safe to run repeatedly and on databases without the table at all (those are
    left entirely to ``init_db``).
    """
    connection = sqlite3.connect(str(database_path), timeout=30)
    try:
        added = _add_missing_columns(connection, "accounts", _VERIFICATION_COLUMNS)
        connection.commit()
        return added
    finally:
        connection.close()


def migrate_subscriptions(database_path: Path) -> list[str]:
    """Add missing webhook-decoded columns to ``subscriptions`` (idempotent)."""
    connection = sqlite3.connect(str(database_path), timeout=30)
    try:
        added = _add_missing_columns(connection, "subscriptions", _SUBSCRIPTION_COLUMNS)
        connection.commit()
        return added
    finally:
        connection.close()


def main() -> int:
    database_url = os.getenv("APP_DATABASE_URL", Settings().database_url)
    try:
        path = database_path_from_url(database_url)
    except ValueError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1

    if not path.is_file():
        # Nothing to migrate; init_db will create the full schema on first boot.
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "ok",
                    "database": str(path),
                    "added": [],
                    "note": "database file does not exist yet; init_db will create it",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0

    try:
        added = migrate_accounts(path)
        added += migrate_subscriptions(path)
    except sqlite3.Error as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1

    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "ok",
                "database": str(path),
                "added": added,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
