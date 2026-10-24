"""Email verification closed loop (ticket #21): issuance, confirmation, expiry.

Everything is exercised through the in-process HTTP seam with fake adapters and a
FrozenClock. The observable surface is the in-memory inbox (``adapters.email_sender``),
HTTP status codes, the unified error envelope and the ``/api/me`` representation.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from app.config import Settings
from app.container import Adapters
from app.main import create_app
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from tests.fakes import FrozenClock, make_fake_adapters

ORIGIN = {"Origin": "http://testserver"}
PASSWORD = "correct-horse"
_TOKEN_IN_LINK = re.compile(r"token=([A-Za-z0-9_\-]+)")


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def register(
    client: AsyncClient,
    *,
    email: str = "learner@example.com",
    password: str = PASSWORD,
    expect: int = 201,
) -> Any:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == expect, response.text
    return response


def sent_emails(adapters: Adapters) -> list[Any]:
    return adapters.email_sender.sent  # type: ignore[attr-defined]


def verification_token(adapters: Adapters, index: int = 0) -> str:
    """Extract the one-time token from the verification link of a delivered email."""
    match = _TOKEN_IN_LINK.search(sent_emails(adapters)[index].body)
    assert match is not None, "no verification token in the delivered email"
    return match.group(1)


async def test_register_delivers_one_verification_email_with_a_return_link(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client, email="Learner@Example.com")

    inbox = sent_emails(adapters)
    assert len(inbox) == 1
    message = inbox[0]
    assert message.to == "learner@example.com"
    assert message.subject
    # The body carries a product return link containing the one-time token.
    assert verification_token(adapters)
    assert "/verify-email?token=" in message.body


async def test_a_verification_email_is_sent_only_once_even_across_logins(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client)
    await client.post("/api/auth/logout", headers=ORIGIN)
    await client.post(
        "/api/auth/login", json={"email": "learner@example.com", "password": PASSWORD}
    )

    assert len(sent_emails(adapters)) == 1


async def test_register_starts_unverified_and_confirmation_is_persisted_and_visible(
    client: AsyncClient, adapters: Adapters
) -> None:
    registered = await register(client)

    before = await client.get("/api/me", headers=bearer(registered))
    assert before.status_code == 200, before.text
    assert before.json()["account"]["email_verified_at"] is None

    confirm = await client.post(
        "/api/auth/verification/confirm", json={"token": verification_token(adapters)}
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["email"] == "learner@example.com"
    assert confirm.json()["email_verified_at"] == "2026-01-15T08:00:00+00:00"

    after = await client.get("/api/me", headers=bearer(registered))
    assert after.json()["account"]["email_verified_at"] == "2026-01-15T08:00:00+00:00"


async def test_confirm_rejects_an_unknown_token(client: AsyncClient) -> None:
    response = await client.post("/api/auth/verification/confirm", json={"token": "bogus"})

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "verification_token_invalid"


async def test_a_verified_token_cannot_be_reused(client: AsyncClient, adapters: Adapters) -> None:
    await register(client)
    token = verification_token(adapters)

    first = await client.post("/api/auth/verification/confirm", json={"token": token})
    assert first.status_code == 200, first.text

    replay = await client.post("/api/auth/verification/confirm", json={"token": token})
    assert replay.status_code == 400, replay.text
    assert replay.json()["error"]["code"] == "verification_token_invalid"


async def test_expired_token_is_rejected_with_a_resend_hint(
    client: AsyncClient, adapters: Adapters
) -> None:
    registered = await register(client)
    # Default TTL is 24h from issue (2026-01-15T08:00Z); step just past it.
    adapters.clock.advance(days=1, seconds=1)  # type: ignore[attr-defined]

    response = await client.post(
        "/api/auth/verification/confirm", json={"token": verification_token(adapters)}
    )

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "verification_token_expired"
    assert "已过期，请重新发送" in error["message"]

    me = await client.get("/api/me", headers=bearer(registered))
    assert me.json()["account"]["email_verified_at"] is None


async def test_token_lifetime_follows_the_configured_ttl(settings: Settings) -> None:
    """A 1-hour TTL expires the link long before the 24-hour default would."""
    tuned = settings.model_copy(update={"email_verification_token_ttl_hours": 1})
    adapters = make_fake_adapters()
    app = create_app(settings=tuned, adapters=adapters)

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            await register(client)
            adapters.clock.advance(seconds=3600 + 1)  # type: ignore[attr-defined]

            response = await client.post(
                "/api/auth/verification/confirm", json={"token": verification_token(adapters)}
            )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "verification_token_expired"
