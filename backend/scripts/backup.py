"""Daily SQLite backup using the online backup API.

Usage (inside the api image or any environment with the backend dependencies)::

    APP_DATABASE_URL=sqlite+aiosqlite:////data/app.db \
    BACKUP_DIR=/backups BACKUP_RETENTION=7 \
    python -m scripts.backup

The copy is consistent while the API keeps writing (SQLite ``Connection.backup`` takes a
snapshot that includes committed WAL content), and each file is verified with
``PRAGMA integrity_check`` before old backups are pruned.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.timeutil import SHANGHAI
from sqlalchemy.engine import make_url

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
DEFAULT_BACKUP_DIR = "./data/backups"
DEFAULT_RETENTION = 7
_BACKUP_GLOB = "app-*.db"


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int
    pruned: tuple[Path, ...]


def database_path_from_url(database_url: str) -> Path:
    """Turn ``sqlite+aiosqlite:///...`` into the on-disk database path."""
    url = make_url(database_url)
    if not url.database:
        raise ValueError(f"database URL has no file path: {database_url!r}")
    return Path(url.database)


def _backup_name(moment: datetime) -> str:
    stamp = moment.astimezone(SHANGHAI).strftime("%Y%m%d-%H%M%S")
    return f"app-{stamp}.db"


def create_backup(
    *,
    database_path: Path | None = None,
    database_url: str | None = None,
    backup_dir: Path,
    retention: int = DEFAULT_RETENTION,
    timestamp: datetime | None = None,
) -> BackupResult:
    """Write one verified backup and prune everything older than ``retention`` files."""
    if database_path is None:
        database_path = database_path_from_url(database_url or DEFAULT_DATABASE_URL)
    database_path = Path(database_path)
    if not database_path.is_file():
        raise FileNotFoundError(f"database not found: {database_path}")

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    moment = timestamp or datetime.now(UTC)
    target = backup_dir / _backup_name(moment)
    if target.exists():
        # Two runs within the same second: keep both instead of overwriting.
        target = backup_dir / f"app-{moment.astimezone(SHANGHAI):%Y%m%d-%H%M%S-%f}.db"

    source = sqlite3.connect(str(database_path), timeout=30)
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            destination.close()
    finally:
        source.close()

    if str(integrity).lower() != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"backup failed integrity_check: {integrity}")

    pruned = _prune(backup_dir, retention, keep=target)
    return BackupResult(path=target, size_bytes=target.stat().st_size, pruned=pruned)


def _prune(backup_dir: Path, retention: int, *, keep: Path) -> tuple[Path, ...]:
    if retention < 1:
        return ()
    backups = sorted(backup_dir.glob(_BACKUP_GLOB), key=lambda path: path.name)
    if keep not in backups:
        backups.append(keep)
        backups.sort(key=lambda path: path.name)
    removable = [path for path in backups if path != keep][: max(0, len(backups) - retention)]
    pruned = []
    for path in removable:
        path.unlink(missing_ok=True)
        pruned.append(path)
    return tuple(pruned)


def main() -> int:
    database_url = os.getenv("APP_DATABASE_URL", DEFAULT_DATABASE_URL)
    backup_dir = Path(os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR))
    try:
        retention = int(os.getenv("BACKUP_RETENTION", str(DEFAULT_RETENTION)))
    except ValueError:
        retention = DEFAULT_RETENTION

    try:
        result = create_backup(
            database_url=database_url,
            backup_dir=backup_dir,
            retention=retention,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports, never crashes with a traceback
        print(
            json.dumps(
                {"timestamp": datetime.now(UTC).isoformat(), "status": "error", "error": str(exc)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1

    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "ok",
                "backup": str(result.path),
                "size_bytes": result.size_bytes,
                "pruned": [str(path) for path in result.pruned],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
