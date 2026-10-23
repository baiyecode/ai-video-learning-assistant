"""Health probes for database, media disk and the running process.

Each probe returns a JSON-ready dict with ``ok`` plus diagnostic details. Probes never
raise: ``/health`` must be able to report the failure it observed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("app.ops.health")

_PROBE_TABLE = "_ops_health_probe"


async def check_database(sessionmaker: async_sessionmaker[AsyncSession]) -> dict:
    """Read (``quick_check``) and write (rolled-back probe row) through the app engine."""
    try:
        async with sessionmaker() as session:
            quick_check = str((await session.execute(text("PRAGMA quick_check"))).scalar_one()).lower()
            journal_mode = str((await session.execute(text("PRAGMA journal_mode"))).scalar_one()).lower()
            # The write is rolled back, so the probe leaves no schema or data behind.
            await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_PROBE_TABLE} (id INTEGER)"))
            await session.execute(text(f"INSERT INTO {_PROBE_TABLE} DEFAULT VALUES"))
            await session.rollback()
    except Exception:  # noqa: BLE001 - health must report any failure, never raise
        logger.warning("health_database_check_failed", exc_info=True)
        return {"ok": False, "error": "database_check_failed", "writable": False}

    result = {
        "ok": quick_check == "ok",
        "quick_check": quick_check,
        "journal_mode": journal_mode,
        "writable": True,
    }
    if not result["ok"]:
        result["error"] = "database_integrity_check_failed"
    return result


def check_disk(directory: Path) -> dict:
    """Write and remove a probe file in the media directory."""
    probe = directory / f".health-{uuid4().hex}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        return {"ok": True, "path": str(directory), "writable": True}
    except OSError:
        logger.warning("health_disk_check_failed", exc_info=True)
        return {"ok": False, "path": str(directory), "writable": False, "error": "media_dir_not_writable"}
    finally:
        probe.unlink(missing_ok=True)


def check_process() -> dict:
    return {"ok": True, "pid": os.getpid()}
