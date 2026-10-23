from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from scripts.backup import create_backup, database_path_from_url, main

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO notes (body) VALUES ('可恢复的数据')")
        connection.commit()
    finally:
        connection.close()


def test_backup_produces_a_restorable_sqlite_database(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    _make_database(database)

    result = create_backup(
        database_path=database,
        backup_dir=tmp_path / "backups",
        timestamp=datetime(2026, 10, 23, 8, 0, 0, tzinfo=SHANGHAI),
    )

    assert result.path.exists()
    assert result.path.parent == tmp_path / "backups"
    assert result.path.name == "app-20261023-080000.db"

    with closing(sqlite3.connect(result.path)) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT body FROM notes").fetchone()[0] == "可恢复的数据"


def test_backup_prunes_old_backups_but_keeps_the_newest(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    _make_database(database)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for stamp in ("20260101-010101", "20260102-010101", "20260103-010101"):
        (backup_dir / f"app-{stamp}.db").write_bytes(b"old")

    result = create_backup(
        database_path=database,
        backup_dir=backup_dir,
        retention=2,
        timestamp=datetime(2026, 1, 4, 1, 1, 1, tzinfo=SHANGHAI),
    )

    remaining = sorted(path.name for path in backup_dir.glob("app-*.db"))
    assert remaining == ["app-20260103-010101.db", result.path.name]
    assert result.pruned == (
        backup_dir / "app-20260101-010101.db",
        backup_dir / "app-20260102-010101.db",
    )


def test_backup_fails_clearly_when_the_database_is_missing(tmp_path: Path) -> None:
    try:
        create_backup(database_path=tmp_path / "missing.db", backup_dir=tmp_path / "backups")
    except FileNotFoundError as exc:
        assert "missing.db" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("expected FileNotFoundError")


def test_database_path_is_parsed_from_the_async_url() -> None:
    assert database_path_from_url("sqlite+aiosqlite:////data/app.db") == Path("/data/app.db")
    assert database_path_from_url("sqlite+aiosqlite:///./data/app.db") == Path("./data/app.db")


def test_backup_captures_committed_rows_still_in_the_wal(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        writer.execute("INSERT INTO notes (body) VALUES ('wal row')")
        writer.commit()
        assert (tmp_path / "app.db-wal").exists()

        result = create_backup(database_path=database, backup_dir=tmp_path / "backups")
    finally:
        writer.close()

    with closing(sqlite3.connect(result.path)) as restored:
        assert restored.execute("SELECT body FROM notes").fetchone()[0] == "wal row"


def test_cli_backs_up_using_environment_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "app.db"
    _make_database(database)
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite+aiosqlite:///{database.as_posix()}")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("BACKUP_RETENTION", "7")

    exit_code = main()

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["status"] == "ok"
    assert Path(report["backup"]).is_file()
