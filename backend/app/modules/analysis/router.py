"""Analysis HTTP routes: create, detail and the SSE stream.

Routes here are mounted under ``/api``. Every route requires a Session Account and
filters by ``account_id``; another Account's Analysis is indistinguishable from a
missing one (404 ``analysis_not_found``).

SSE contract (shared with the SPA)::

    meta → delta* → mindmap → done          (success)
    meta → error                            (failure)

``meta``/``delta``/``mindmap``/``done``/``error`` are the only event names. Payloads
are JSON objects (single-line ``data:`` frames). Reconnecting replays the persisted
summary as ``delta`` frames before continuing; a finished Analysis is replayed in
full. Disconnecting never cancels generation because it runs as its own task.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.container import Adapters
from app.deps import (
    get_adapters,
    get_current_account,
    get_rate_limiter,
    get_session,
    get_settings,
)
from app.errors import ErrorCode
from app.modules.identity.models import Account
from app.ratelimit import RateLimiter

from . import history, service
from .manager import AnalysisManager
from .models import Analysis, AnalysisStatus
from .schemas import AnalysisHistoryItemOut, AnalysisOut, CreateAnalysisRequest

router = APIRouter(prefix="/analyses", tags=["analysis"])

_MANAGER_STATE_KEY = "analysis_manager"
_POLL_INTERVAL_SECONDS = 0.05


def get_analysis_manager(request: Request) -> AnalysisManager:
    """Lazily attach the generation runner to ``app.state`` (keeps ``main.py`` untouched)."""
    manager: AnalysisManager | None = getattr(request.app.state, _MANAGER_STATE_KEY, None)
    if manager is None:
        state = request.app.state
        manager = AnalysisManager(
            sessionmaker=state.sessionmaker,
            adapters=state.adapters,
            settings=state.settings,
        )
        setattr(state, _MANAGER_STATE_KEY, manager)
    return manager


@router.post("", response_model=AnalysisOut, status_code=201)
async def create_analysis(
    payload: CreateAnalysisRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    adapters: Adapters = Depends(get_adapters),
    account: Account = Depends(get_current_account),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> AnalysisOut:
    result = await service.create_analysis(
        session,
        adapters.clock,
        settings,
        account_id=account.id,
        video_id=payload.video_id,
        force=payload.force,
        rate_limiter=rate_limiter,
        budget_ledger=adapters.budget_ledger,
    )
    if result.created:
        get_analysis_manager(request).submit(result.analysis.id)
    else:
        # Reused in-progress or already completed Analysis: nothing new was reserved.
        response.status_code = 200
    return service.to_out(result.analysis, result.video)


@router.get("", response_model=list[AnalysisHistoryItemOut])
async def list_analysis_history(
    session: AsyncSession = Depends(get_session),
    account: Account = Depends(get_current_account),
) -> list[AnalysisHistoryItemOut]:
    """The current Account's Analyses, newest first. Other Accounts never appear."""
    return await history.list_analyses(session, account.id)


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: str,
    session: AsyncSession = Depends(get_session),
    account: Account = Depends(get_current_account),
) -> AnalysisOut:
    analysis, video = await service.get_analysis(session, account.id, analysis_id)
    return service.to_out(analysis, video)


@router.get("/{analysis_id}/stream")
async def stream_analysis(
    analysis_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    account: Account = Depends(get_current_account),
) -> StreamingResponse:
    await service.get_analysis(session, account.id, analysis_id)
    return StreamingResponse(
        _event_stream(request.app.state.sessionmaker, analysis_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _event(name: str, payload: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _event_stream(sessionmaker, analysis_id: str) -> AsyncIterator[str]:
    """Replay persisted state, then follow the row until it reaches a terminal status."""
    sent_meta = False
    sent_summary = 0

    while True:
        async with sessionmaker() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                yield _event(
                    "error",
                    {
                        "code": ErrorCode.ANALYSIS_NOT_FOUND.value,
                        "message": service.MESSAGE_ANALYSIS_NOT_FOUND,
                    },
                )
                return
            status = analysis.status
            summary = analysis.summary_markdown or ""
            mindmap = analysis.mindmap_markdown or ""
            error_code = analysis.error_code
            meta = {
                "analysis_id": analysis.id,
                "video_id": analysis.video_id,
                "status": status,
                "subtitle_source": analysis.subtitle_source,
                "truncated": bool(analysis.truncated),
            }

        if not sent_meta:
            yield _event("meta", meta)
            sent_meta = True

        if len(summary) > sent_summary:
            yield _event("delta", {"text": summary[sent_summary:]})
            sent_summary = len(summary)

        if status == AnalysisStatus.COMPLETED.value:
            yield _event("mindmap", {"markdown": mindmap})
            yield _event("done", {"status": AnalysisStatus.COMPLETED.value})
            return
        if status == AnalysisStatus.FAILED.value:
            code = error_code or ErrorCode.ANALYSIS_FAILED.value
            yield _event("error", {"code": code, "message": service.error_message(code)})
            return

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
