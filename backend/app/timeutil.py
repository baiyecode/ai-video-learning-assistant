"""Time helpers shared by every module.

Two facts drive this file: SQLite round-trips timezone-aware datetimes as naive UTC
values, so each module that reads a timestamp column normalises it through
:func:`as_utc`; and the product's daily reset is the Asia/Shanghai calendar day,
regardless of where the server runs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


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


def shanghai_day(value: datetime) -> date:
    """The Asia/Shanghai calendar day ``value`` falls on."""
    return required_utc(value).astimezone(SHANGHAI).date()


def next_shanghai_midnight(now: datetime) -> datetime:
    """The next Asia/Shanghai midnight after ``now``, as a timezone-aware instant."""
    next_day = shanghai_day(now) + timedelta(days=1)
    return datetime(next_day.year, next_day.month, next_day.day, tzinfo=SHANGHAI)
