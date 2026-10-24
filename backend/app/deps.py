"""Request-scoped dependencies, including authentication."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .container import Adapters
from .errors import AppError, ErrorCode
from .modules.identity.models import Account
from .modules.identity.security import AccessTokenError, decode_access_token
from .ports import Clock
from .ratelimit import RateLimiter, build_rules


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_adapters(request: Request) -> Adapters:
    return request.app.state.adapters


def get_clock(adapters: Adapters = Depends(get_adapters)) -> Clock:
    return adapters.clock


def get_rate_limiter(request: Request, settings: Settings = Depends(get_settings)) -> RateLimiter:
    """One in-memory limiter per application instance (created lazily on first use)."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        adapters = request.app.state.adapters
        limiter = RateLimiter(clock=adapters.clock, rules=build_rules(settings))
        request.app.state.rate_limiter = limiter
    return limiter


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _account_from_bearer(
    request: Request,
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
) -> Account | None:
    token = _bearer_token(request)
    if token is None:
        return None
    try:
        account_id = decode_access_token(token, settings, now=clock.now())
    except AccessTokenError:
        return None
    return await session.get(Account, account_id)


def _auth_required() -> AppError:
    return AppError(401, ErrorCode.AUTH_REQUIRED, "请先登录")


async def get_current_account(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> Account:
    """Require a valid ``Authorization: Bearer`` access token; 401 ``auth_required`` otherwise."""
    account = await _account_from_bearer(request, session, settings, clock)
    if account is None:
        raise _auth_required()
    return account


async def get_optional_account(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> Account | None:
    """Anonymous-friendly variant: returns ``None`` instead of raising when unauthenticated."""
    return await _account_from_bearer(request, session, settings, clock)
