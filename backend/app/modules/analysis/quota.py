"""Daily Quota bookkeeping for Analysis.

Quota is counted in Analyses per Account per Asia/Shanghai calendar day. Creation
reserves one unit, success moves it to ``consumed`` and failure releases it. Viewing
an existing result never touches these counters.

``reserve`` is a single atomic SQLite upsert so two concurrent create requests can
never both win the same unit. VIP Membership lifts the cap by passing the
``UNLIMITED_DAILY_LIMIT`` sentinel as the ``limit``: the same upsert still counts
the unit (so failure rollback is untouched), it just never checks a bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ports import Clock
from app.timeutil import next_shanghai_midnight

from .models import QuotaUsage

#: Sentinel ``limit``/``daily_limit``/``remaining`` value meaning "no cap" (VIP Membership).
UNLIMITED_DAILY_LIMIT = -1


def is_unlimited(limit: int) -> bool:
    """Whether a Quota limit expresses VIP Membership's "unlimited" semantics."""
    return limit == UNLIMITED_DAILY_LIMIT


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    daily_limit: int
    used: int
    remaining: int
    resets_at: datetime


def next_reset_at(clock: Clock) -> datetime:
    """The next Asia/Shanghai midnight: when the daily Quota allowance renews."""
    return next_shanghai_midnight(clock.now())


async def reserve(session: AsyncSession, account_id: str, day: date, limit: int) -> bool:
    """Atomically reserve one unit. Returns ``False`` when the daily limit is reached.

    ``limit`` may be :data:`UNLIMITED_DAILY_LIMIT` (VIP Membership): the reservation
    is then unconditional, but still counted, keeping rollback on failure intact.
    The caller must commit (or roll back) the surrounding transaction.
    """
    statement = sqlite_insert(QuotaUsage).values(
        account_id=account_id, day=day, reserved=1, consumed=0
    )
    if is_unlimited(limit):
        statement = statement.on_conflict_do_update(
            index_elements=[QuotaUsage.account_id, QuotaUsage.day],
            set_={"reserved": QuotaUsage.reserved + 1},
        )
    else:
        statement = statement.on_conflict_do_update(
            index_elements=[QuotaUsage.account_id, QuotaUsage.day],
            set_={"reserved": QuotaUsage.reserved + 1},
            where=(QuotaUsage.reserved + QuotaUsage.consumed) < limit,
        )
    result = await session.execute(statement)
    return result.rowcount == 1


async def consume(session: AsyncSession, account_id: str, day: date) -> None:
    """Move one reserved unit to consumed after a successful generation."""
    await session.execute(
        update(QuotaUsage)
        .where(
            QuotaUsage.account_id == account_id,
            QuotaUsage.day == day,
            QuotaUsage.reserved > 0,
        )
        .values(reserved=QuotaUsage.reserved - 1, consumed=QuotaUsage.consumed + 1)
    )


async def release(session: AsyncSession, account_id: str, day: date) -> None:
    """Return a reserved unit after a failed generation."""
    await session.execute(
        update(QuotaUsage)
        .where(
            QuotaUsage.account_id == account_id,
            QuotaUsage.day == day,
            QuotaUsage.reserved > 0,
        )
        .values(reserved=QuotaUsage.reserved - 1)
    )


async def usage(session: AsyncSession, account_id: str, clock: Clock, limit: int) -> QuotaSnapshot:
    row = await session.scalar(
        select(QuotaUsage).where(
            QuotaUsage.account_id == account_id,
            QuotaUsage.day == clock.today(),
        )
    )
    used = (row.reserved + row.consumed) if row is not None else 0
    return QuotaSnapshot(
        daily_limit=limit,
        used=used,
        remaining=UNLIMITED_DAILY_LIMIT if is_unlimited(limit) else max(0, limit - used),
        resets_at=next_reset_at(clock),
    )
