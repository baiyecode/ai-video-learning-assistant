"""Password hashing, opaque refresh tokens and signed access tokens.

Passwords are stored with bcrypt over a SHA-256 digest of the UTF-8 password: bcrypt only
consumes 72 bytes, and hashing the digest first keeps arbitrarily long passwords safe from
silent truncation. Refresh tokens are opaque random strings; only their SHA-256 hash is
persisted. Access tokens are short-lived HS256 JWTs and are never stored.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Response

from app.config import Settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
# Dummy hash verified for unknown accounts so login timing does not reveal registration.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    hashlib.sha256(b"timing-equalizer").digest(), bcrypt.gensalt()
).decode()


class AccessTokenError(Exception):
    """The bearer token is missing a valid signature, type, subject or lifetime."""


def _password_digest(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_digest(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_password_digest(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def verify_dummy_password(password: str) -> None:
    """Spend the same bcrypt time as a real verification, without any account."""
    verify_password(password, _DUMMY_PASSWORD_HASH)


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _signing_key(settings: Settings) -> bytes:
    """Derive a full-length HMAC key so short configured secrets still meet HS256 guidance."""
    return hashlib.sha256(f"jwt:{settings.jwt_signing_key}".encode()).digest()


def encode_access_token(
    account_id: str, settings: Settings, *, now: datetime
) -> tuple[str, datetime]:
    """Return ``(jwt, expires_at)``. Expiry is evaluated against the injected Clock."""
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": account_id,
        "typ": ACCESS_TOKEN_TYPE,
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, _signing_key(settings), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str, settings: Settings, *, now: datetime) -> str:
    """Validate signature/shape/lifetime and return the Account id."""
    try:
        payload = jwt.decode(
            token,
            _signing_key(settings),
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False, "verify_iat": False},
        )
    except jwt.PyJWTError as exc:  # includes malformed tokens, wrong alg and bad signatures
        raise AccessTokenError from exc

    subject = payload.get("sub")
    expires_at = payload.get("exp")
    if payload.get("typ") != ACCESS_TOKEN_TYPE or not isinstance(subject, str) or not subject:
        raise AccessTokenError
    if not isinstance(expires_at, (int, float)):
        raise AccessTokenError
    if datetime.fromtimestamp(expires_at, UTC) <= now:
        raise AccessTokenError
    return subject


def ensure_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo; treat stored values as UTC and normalise for comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


__all__ = [
    "AccessTokenError",
    "clear_refresh_cookie",
    "decode_access_token",
    "encode_access_token",
    "ensure_utc",
    "hash_password",
    "hash_refresh_token",
    "new_refresh_token",
    "set_refresh_cookie",
    "verify_dummy_password",
    "verify_password",
]
