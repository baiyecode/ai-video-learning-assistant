from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


class SystemClock:
    """Real clock: UTC instants, Asia/Shanghai calendar dates for Quota."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().astimezone(SHANGHAI).date()
