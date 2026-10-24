"""SQLAlchemy models for ops (abuse reports; budget ledger/maintenance land here too).

A Report is a traceable record of an abuse or copyright complaint submitted from the
Terms page. It intentionally stores no evidence payload: the submitted URL, reason,
optional contact and free-form details are enough for a human to follow up.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    reason: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="received", index=True)

    # Traceability only: reporting stays open to Visitors (ticket #12 adds throttling).
    visitor_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BudgetSpend(Base):
    """Global AI spend per Asia/Shanghai calendar day.

    One row per day; ``spent_usd`` is incremented atomically after each Summarizer
    call. The day key comes from the injected Clock, so tests can cross midnight.
    """

    __tablename__ = "budget_spend"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
