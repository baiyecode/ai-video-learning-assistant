"""SQLite-backed daily USD budget ledger (ticket #12).

One row per Asia/Shanghai calendar day in ``budget_spend``. ``record`` is an atomic
upsert so concurrent Analysis tasks cannot lose spend. The day key comes from the
injected Clock (production: ``SystemClock``; tests: ``FrozenClock``).
"""

from __future__ import annotations

import math

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.modules.ops.models import BudgetSpend
from app.ports import Clock


class DbBudgetLedger:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._settings = settings

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:  # pragma: no cover - production always binds
            raise RuntimeError("DbBudgetLedger is not bound to a sessionmaker")
        return self._sessionmaker

    async def spent_today(self) -> float:
        async with self._sessions()() as session:
            row = await session.get(BudgetSpend, self._clock.today())
            return float(row.spent_usd) if row is not None else 0.0

    async def can_spend(self, estimated_usd: float) -> bool:
        budget = self._settings.daily_budget_usd
        if budget <= 0:
            return False
        return await self.spent_today() + max(0.0, estimated_usd) <= budget

    async def record(self, usd: float) -> None:
        amount = float(usd)
        if not math.isfinite(amount) or amount <= 0:
            return
        day = self._clock.today()
        statement = sqlite_insert(BudgetSpend).values(day=day, spent_usd=amount)
        statement = statement.on_conflict_do_update(
            index_elements=[BudgetSpend.day],
            set_={"spent_usd": BudgetSpend.spent_usd + amount},
        )
        async with self._sessions()() as session:
            await session.execute(statement)
            await session.commit()
