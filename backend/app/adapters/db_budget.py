"""SQLite-backed daily USD budget ledger. Implemented by tickets #8/#12."""

from __future__ import annotations


class DbBudgetLedger:
    async def can_spend(self, estimated_usd: float) -> bool:
        raise NotImplementedError("DbBudgetLedger.can_spend is implemented in ticket #8")

    async def record(self, usd: float) -> None:
        raise NotImplementedError("DbBudgetLedger.record is implemented in ticket #8")
