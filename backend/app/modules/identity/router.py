"""Identity HTTP routes: register, login, refresh, logout and ``/api/me``.

Mounted under ``/api`` by ``main.py``. Refresh tokens travel only in an HttpOnly cookie and
rotate on every refresh; the database stores just their SHA-256 hash. Access tokens are
15-minute JWTs passed as ``Authorization: Bearer``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.container import Adapters
from app.deps import get_adapters, get_clock, get_current_account, get_rate_limiter, get_session, get_settings
from app.errors import AppError, ErrorCode
from app.http import client_ip
from app.modules.analysis import service as analysis_service
from app.modules.analysis.schemas import QuotaOut
from app.modules.identity.models import Account, Session
from app.modules.identity.security import (
    clear_refresh_cookie,
    encode_access_token,
    hash_password,
    hash_refresh_token,
    hash_verification_token,
    new_refresh_token,
    set_refresh_cookie,
    verify_dummy_password,
    verify_password,
)
from app.modules.identity.verification import issue_verification_token, verification_email
from app.ports import Clock
from app.ratelimit import RateLimiter
from app.timeutil import required_utc

router = APIRouter(tags=["identity"])

logger = logging.getLogger("app.identity")

PASSWORD_MIN_LENGTH = 8
_MESSAGE_SESSION_INVALID = "登录状态已失效，请重新登录"


class Credentials(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class AccountOut(BaseModel):
    id: str
    email: str
    created_at: str
    # Email verification state (ticket #21). ``None`` until the one-time link is confirmed.
    email_verified_at: str | None = None


class AuthResponse(BaseModel):
    account: AccountOut
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    account: AccountOut
    quota: QuotaOut


class ConfirmVerificationRequest(BaseModel):
    token: str


def _account_out(account: Account) -> AccountOut:
    verified_at = account.email_verified_at
    return AccountOut(
        id=account.id,
        email=account.email,
        created_at=required_utc(account.created_at).isoformat(),
        email_verified_at=required_utc(verified_at).isoformat() if verified_at else None,
    )


def _auth_response(account: Account, token: str, expires_at: datetime, settings: Settings) -> dict:
    del expires_at  # lifetime is conveyed as a relative value
    return {
        "account": _account_out(account),
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_minutes * 60,
    }


def _require_origin(request: Request, settings: Settings) -> None:
    """Refresh/logout are cookie-authenticated, so cross-site POSTs must be refused.

    Missing ``Origin`` is allowed for non-browser clients; otherwise the origin must be
    the API's own origin or one explicitly allowed in ``APP_CORS_ORIGINS``.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    own_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin.rstrip("/") in {o.rstrip("/") for o in settings.cors_origins} | {own_origin}:
        return
    raise AppError(403, ErrorCode.SESSION_INVALID, _MESSAGE_SESSION_INVALID)


def _session_invalid() -> AppError:
    return AppError(401, ErrorCode.SESSION_INVALID, _MESSAGE_SESSION_INVALID)


async def _issue_session(
    db: AsyncSession,
    account: Account,
    settings: Settings,
    clock: Clock,
    *,
    user_agent: str | None,
) -> str:
    """Create a Session row for a fresh opaque refresh token and return the raw token."""
    now = clock.now()
    raw_token = new_refresh_token()
    db.add(
        Session(
            account_id=account.id,
            refresh_token_hash=hash_refresh_token(raw_token),
            issued_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=(user_agent or "")[:512] or None,
        )
    )
    return raw_token


async def _find_session(db: AsyncSession, raw_token: str) -> Session | None:
    return await db.scalar(
        select(Session).where(Session.refresh_token_hash == hash_refresh_token(raw_token))
    )


@router.post(
    "/auth/register",
    response_model=AuthResponse,
    status_code=201,
    summary="Create an Account and start a Session",
)
async def register(
    payload: Credentials,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    adapters: Adapters = Depends(get_adapters),
) -> dict:
    rate_limiter.hit("auth.register", client_ip(request))
    if len(payload.password) < PASSWORD_MIN_LENGTH:
        raise AppError(400, ErrorCode.WEAK_PASSWORD, f"密码至少需要 {PASSWORD_MIN_LENGTH} 位")

    email = payload.email.strip().lower()
    if await db.scalar(select(Account).where(Account.email == email)) is not None:
        raise AppError(409, ErrorCode.EMAIL_TAKEN, "该邮箱已注册，请直接登录")

    password_hash = await asyncio.to_thread(hash_password, payload.password)
    account = Account(email=email, password_hash=password_hash, created_at=clock.now())
    db.add(account)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, ErrorCode.EMAIL_TAKEN, "该邮箱已注册，请直接登录") from None

    refresh_token = await _issue_session(
        db, account, settings, clock, user_agent=request.headers.get("user-agent")
    )
    verification_token = issue_verification_token(account, settings, clock)
    await db.commit()

    # A delivery failure must not undo a successful registration; the verification
    # email can be re-sent (ticket #22).
    try:
        await adapters.email_sender.send(verification_email(account, settings, verification_token))
    except Exception:
        logger.warning("verification_email_delivery_failed", exc_info=True)

    access_token, expires_at = encode_access_token(account.id, settings, now=clock.now())
    set_refresh_cookie(response, refresh_token, settings)
    return _auth_response(account, access_token, expires_at, settings)


@router.post("/auth/login", response_model=AuthResponse, summary="Start a Session")
async def login(
    payload: Credentials,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict:
    rate_limiter.hit("auth.login", client_ip(request))
    account = await db.scalar(select(Account).where(Account.email == payload.email.strip().lower()))

    if account is None:
        # Burn the same bcrypt time as a real check so unknown emails are indistinguishable.
        await asyncio.to_thread(verify_dummy_password, payload.password)
        raise AppError(401, ErrorCode.INVALID_CREDENTIALS, "邮箱或密码不正确")

    valid = await asyncio.to_thread(verify_password, payload.password, account.password_hash)
    if not valid:
        raise AppError(401, ErrorCode.INVALID_CREDENTIALS, "邮箱或密码不正确")

    refresh_token = await _issue_session(
        db, account, settings, clock, user_agent=request.headers.get("user-agent")
    )
    await db.commit()

    access_token, expires_at = encode_access_token(account.id, settings, now=clock.now())
    set_refresh_cookie(response, refresh_token, settings)
    return _auth_response(account, access_token, expires_at, settings)


@router.post("/auth/refresh", response_model=AuthResponse, summary="Rotate the Session")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> dict:
    _require_origin(request, settings)

    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise _session_invalid()

    record = await _find_session(db, raw_token)
    now = clock.now()
    if record is None or record.revoked_at is not None or required_utc(record.expires_at) <= now:
        raise _session_invalid()

    account = await db.get(Account, record.account_id)
    if account is None:
        raise _session_invalid()

    # Atomic single-use rotation: a concurrent replay can only revoke once.
    revoked = await db.execute(
        update(Session)
        .where(Session.id == record.id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if revoked.rowcount != 1:
        await db.rollback()
        raise _session_invalid()

    new_token = await _issue_session(
        db,
        account,
        settings,
        clock,
        user_agent=record.user_agent or request.headers.get("user-agent"),
    )
    await db.commit()

    access_token, expires_at = encode_access_token(account.id, settings, now=clock.now())
    set_refresh_cookie(response, new_token, settings)
    return _auth_response(account, access_token, expires_at, settings)


@router.post("/auth/logout", status_code=204, summary="Revoke the current Session")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> None:
    _require_origin(request, settings)

    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        await db.execute(
            update(Session)
            .where(
                Session.refresh_token_hash == hash_refresh_token(raw_token),
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=clock.now())
        )
        await db.commit()

    clear_refresh_cookie(response, settings)


def _verification_token_invalid() -> AppError:
    return AppError(400, ErrorCode.VERIFICATION_TOKEN_INVALID, "验证链接无效或已被使用")


@router.post(
    "/auth/verification/confirm",
    response_model=AccountOut,
    summary="Consume a one-time email verification token",
)
async def confirm_verification(
    payload: ConfirmVerificationRequest,
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> AccountOut:
    """Authenticate by the token itself; no session or cookie is required.

    A successful confirmation persists ``email_verified_at`` and clears the stored
    token hash, making the link single-use.
    """
    token_hash = hash_verification_token(payload.token.strip())
    account = await db.scalar(
        select(Account).where(Account.verification_token_hash == token_hash)
    )
    if account is None:
        raise _verification_token_invalid()

    now = clock.now()
    expires_at = account.verification_expires_at
    if expires_at is None or required_utc(expires_at) <= now:
        raise AppError(400, ErrorCode.VERIFICATION_TOKEN_EXPIRED, "验证链接已过期，请重新发送")

    # Atomic single-use consumption: a concurrent replay can only claim the token once.
    consumed = await db.execute(
        update(Account)
        .where(Account.id == account.id, Account.verification_token_hash == token_hash)
        .values(
            email_verified_at=now,
            verification_token_hash=None,
            verification_expires_at=None,
        )
    )
    if consumed.rowcount != 1:
        await db.rollback()
        raise _verification_token_invalid()
    await db.commit()

    account.email_verified_at = now
    account.verification_token_hash = None
    account.verification_expires_at = None
    return _account_out(account)


@router.get("/me", response_model=MeResponse, summary="Current Account and quota")
async def me(
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> dict:
    return {
        "account": _account_out(account),
        "quota": await analysis_service.daily_quota(db, account.id, clock, settings),
    }
