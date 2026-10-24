"""Shared auth-flow helpers (ticket #22): register -> verify -> login.

Registration no longer starts a Session and no longer reveals whether an email is taken,
so a test that needs an authenticated (and, for Analysis, verified) Account composes the
real endpoints instead of assuming register authenticates. Only external HTTP behaviour is
exercised here; the verification token is read back out of the fake inbox's delivered mail.
"""

from __future__ import annotations

import re
from typing import Any

from app.container import Adapters
from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse"
DEFAULT_EMAIL = "learner@example.com"
_TOKEN_IN_LINK = re.compile(r"token=([A-Za-z0-9_\-]+)")


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def verification_token(adapters: Adapters, index: int = -1) -> str:
    """Extract the one-time token from the verification link of a delivered email."""
    inbox: list[Any] = adapters.email_sender.sent  # type: ignore[attr-defined]
    match = _TOKEN_IN_LINK.search(inbox[index].body)
    assert match is not None, "no verification token in the delivered email"
    return match.group(1)


async def register(
    client: AsyncClient,
    *,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    expect: int = 201,
) -> Any:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == expect, response.text
    return response


async def login(
    client: AsyncClient,
    *,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    expect: int = 200,
) -> Any:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == expect, response.text
    return response


async def confirm_email(client: AsyncClient, adapters: Adapters, *, index: int = -1) -> Any:
    response = await client.post(
        "/api/auth/verification/confirm", json={"token": verification_token(adapters, index)}
    )
    assert response.status_code == 200, response.text
    return response


async def verified_account(
    client: AsyncClient,
    adapters: Adapters,
    *,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
) -> dict[str, str]:
    """Register, confirm the verification email and log in; return bearer headers."""
    await register(client, email=email, password=password)
    await confirm_email(client, adapters)
    return bearer(await login(client, email=email, password=password))


async def logged_in_account(
    client: AsyncClient,
    *,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
) -> dict[str, str]:
    """Register and log in without verifying: for endpoints that ignore verification state."""
    await register(client, email=email, password=password)
    return bearer(await login(client, email=email, password=password))
