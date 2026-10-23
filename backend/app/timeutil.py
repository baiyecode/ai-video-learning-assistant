"""UTC datetime helpers.

SQLite round-trips timezone-aware datetimes as naive UTC values, so every module
that reads a timestamp column normalises it through :func:`as_utc`.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as a UTC-aware datetime (naive values are assumed UTC)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def required_utc(value: datetime | None) -> datetime:
    """Like :func:`as_utc` but never returns ``None`` (falls back to now)."""
    return as_utc(value) or datetime.now(UTC)
