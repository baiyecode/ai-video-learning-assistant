"""Request-scoped dependencies. Later tickets add auth dependencies here."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .container import Adapters
from .ports import Clock


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_adapters(request: Request) -> Adapters:
    return request.app.state.adapters


def get_clock(adapters: Adapters = Depends(get_adapters)) -> Clock:
    return adapters.clock


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session
