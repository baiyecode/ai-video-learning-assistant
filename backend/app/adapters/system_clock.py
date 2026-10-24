from __future__ import annotations

from datetime import UTC, date, datetime

from app.timeutil import shanghai_day


class SystemClock:
    """Real clock: UTC instants, Asia/Shanghai calendar dates for Quota."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return shanghai_day(self.now())
