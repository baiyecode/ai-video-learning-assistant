"""Abuse / copyright reports: ``POST /api/reports``.

Reporting is open to Visitors and Accounts alike. Each submission becomes a traceable
row (id + created_at + received status) that operators can follow up on. The reason
is a closed enum so reports stay filterable; URLs are only stored, never fetched.

Rate limiting is ticket #12: ``_rate_limit_hook`` is the seam where that lands.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_clock, get_optional_account, get_session
from app.errors import AppError, ErrorCode
from app.modules.identity.models import Account
from app.ports import Clock

from .models import Report

logger = logging.getLogger("app.ops.reports")

router = APIRouter(prefix="/api/reports", tags=["ops"])

MESSAGE_REPORT_INVALID = "举报内容有误：请选择有效的举报原因，并提供 http 或 https 链接"
MESSAGE_REPORT_INVALID_REASON = "举报原因无效，请从列表中选择"


class ReportReason(StrEnum):
    COPYRIGHT = "copyright"
    DRM_BYPASS = "drm_bypass"
    ABUSE = "abuse"
    OTHER = "other"


class ReportRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    reason: str = Field(min_length=1, max_length=32)
    contact: str | None = Field(default=None, max_length=256)
    details: str | None = Field(default=None, max_length=2000)


class ReportResponse(BaseModel):
    id: str
    created_at: datetime
    status: Literal["received"] = "received"


def _rate_limit_hook(_request: Request) -> None:
    """No-op until ticket #12 adds per-IP throttling for report submissions."""


async def create_report(
    session: AsyncSession,
    clock: Clock,
    payload: ReportRequest,
    *,
    visitor_ip: str | None,
    account_id: str | None,
) -> Report:
    reason = _validated_reason(payload.reason)
    report = Report(
        reason=reason.value,
        url=_optional_text(payload.url),
        contact=_optional_text(payload.contact),
        details=_optional_text(payload.details),
        status="received",
        visitor_ip=visitor_ip,
        account_id=account_id,
        created_at=clock.now(),
    )
    if report.url is not None:
        _validated_url(report.url)

    session.add(report)
    await session.commit()
    logger.info("report_received", extra={"event": "report_received", "reason": report.reason})
    return report


@router.post("", response_model=ReportResponse, status_code=201)
async def submit_report(
    payload: ReportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    clock: Clock = Depends(get_clock),
    account: Account | None = Depends(get_optional_account),
) -> ReportResponse:
    _rate_limit_hook(request)
    report = await create_report(
        session,
        clock,
        payload,
        visitor_ip=_client_ip(request),
        account_id=account.id if account is not None else None,
    )
    return ReportResponse(id=report.id, created_at=_as_aware(report.created_at), status="received")


def _validated_reason(value: str) -> ReportReason:
    try:
        return ReportReason(value.strip().lower())
    except ValueError as exc:
        raise AppError(422, ErrorCode.REPORT_INVALID, MESSAGE_REPORT_INVALID_REASON) from exc


def _validated_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise AppError(422, ErrorCode.REPORT_INVALID, MESSAGE_REPORT_INVALID)
    return value


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = request.client
    return client.host if client is not None else None
