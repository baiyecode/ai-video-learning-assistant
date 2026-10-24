"""Account registration, login, Session refresh/logout and ``/api/me``.

Everything is exercised through the in-process HTTP seam with fake adapters and a
FrozenClock, so token/session expiry is deterministic.

Registration no longer starts a Session and no longer reveals whether an email is taken
(ticket #22): it always answers 201 with a uniform message and authenticates through
``POST /auth/login`` afterwards.
"""

from __future__ import annotations

from typing import Any

from app.container import Adapters
from httpx import AsyncClient

ORIGIN = {"Origin": "http://testserver"}
PASSWORD = "correct-horse"


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


async def login(
    client: AsyncClient,
    *,
    email: str = "learner@example.com",
    password: str = PASSWORD,
    expect: int = 200,
) -> Any:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == expect, response.text
    return response


async def register_and_login(client: AsyncClient, *, email: str = "learner@example.com") -> Any:
    """Create the Account (unverified) and open a Session; returns the login response."""
    await register(client, email=email)
    return await login(client, email=email)


async def test_register_creates_account_without_authenticating(client: AsyncClient) -> None:
    response = await register(client, email="Learner@Example.com")

    body = response.json()
    # A uniform acknowledgement: no Session material, and nothing that says "created".
    assert body == {"message": "如果这是你本人的操作，请查收邮箱中的验证邮件"}
    assert "access_token" not in body
    assert "account" not in body
    assert "set-cookie" not in {k.lower() for k in response.headers}


async def test_login_returns_the_session_and_me_round_trip(client: AsyncClient) -> None:
    await register(client)

    response = await login(client, email="LEARNER@example.COM")
    body = response.json()
    assert body["account"]["email"] == "learner@example.com"
    assert body["account"]["id"]
    assert body["account"]["created_at"]
    assert body["account"]["email_verified_at"] is None
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60

    cookie = response.headers.get("set-cookie", "")
    assert "refresh_token=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()

    me = await client.get("/api/me", headers=bearer(response))
    assert me.status_code == 200
    assert me.json()["account"]["email"] == "learner@example.com"
    assert me.json()["quota"] == {
        "daily_limit": 3,
        "used": 0,
        "remaining": 3,
        "resets_at": "2026-01-16T00:00:00+08:00",
    }


async def test_registering_a_taken_email_does_not_reveal_it(client: AsyncClient) -> None:
    """A second registration for the same email is indistinguishable from the first."""
    first = await register(client, email="learner@example.com")
    second = await register(client, email="Learner@Example.com")

    assert second.status_code == first.status_code == 201
    assert second.json() == first.json()
    # Nothing in the acknowledgement signals that the email was already registered.
    assert "account" not in second.json()
    assert "access_token" not in second.json()


async def test_weak_password_is_rejected(client: AsyncClient) -> None:
    response = await register(client, password="short", expect=400)

    assert response.json()["error"]["code"] == "weak_password"


async def test_invalid_email_is_rejected(client: AsyncClient) -> None:
    response = await register(client, email="not-an-email", expect=422)

    assert response.json()["error"]["code"] == "invalid_request"


async def test_wrong_password_and_unknown_email_share_invalid_credentials(
    client: AsyncClient,
) -> None:
    await register(client, email="learner@example.com")

    wrong_password = await login(client, password="wrong-password", expect=401)
    unknown_email = await login(client, email="nobody@example.com", expect=401)

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


async def test_refresh_rotates_the_token_and_rejects_the_old_one(client: AsyncClient) -> None:
    logged_in = await register_and_login(client)
    old_refresh = client.cookies.get("refresh_token")
    assert old_refresh

    refreshed = await client.post("/api/auth/refresh", headers=ORIGIN)
    assert refreshed.status_code == 200
    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh
    assert refreshed.json()["access_token"] != logged_in.json()["access_token"]
    assert refreshed.json()["account"]["email"] == "learner@example.com"

    me = await client.get("/api/me", headers=bearer(refreshed))
    assert me.status_code == 200

    reused = await client.post(
        "/api/auth/refresh", headers={**ORIGIN, "Cookie": f"refresh_token={old_refresh}"}
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "session_invalid"


async def test_logout_revokes_only_the_current_session(client: AsyncClient) -> None:
    first = await register_and_login(client)
    first_refresh = client.cookies.get("refresh_token")
    assert first_refresh

    second = await login(client)
    assert second.status_code == 200
    second_refresh = client.cookies.get("refresh_token")
    assert second_refresh and second_refresh != first_refresh

    logout = await client.post("/api/auth/logout", headers=ORIGIN)
    assert logout.status_code == 204
    assert client.cookies.get("refresh_token") is None

    revoked = await client.post(
        "/api/auth/refresh", headers={**ORIGIN, "Cookie": f"refresh_token={second_refresh}"}
    )
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "session_invalid"

    # The other device's Session is untouched.
    still_valid = await client.post(
        "/api/auth/refresh", headers={**ORIGIN, "Cookie": f"refresh_token={first_refresh}"}
    )
    assert still_valid.status_code == 200
    assert (await client.get("/api/me", headers=bearer(first))).status_code == 200


async def test_expired_access_token_is_rejected_but_refresh_still_works(
    client: AsyncClient, adapters: Adapters
) -> None:
    response = await register_and_login(client)
    adapters.clock.advance(seconds=15 * 60 + 1)

    expired = await client.get("/api/me", headers=bearer(response))
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "auth_required"

    refreshed = await client.post("/api/auth/refresh", headers=ORIGIN)
    assert refreshed.status_code == 200
    assert (await client.get("/api/me", headers=bearer(refreshed))).status_code == 200


async def test_expired_refresh_session_is_rejected(client: AsyncClient, adapters: Adapters) -> None:
    await register_and_login(client)
    adapters.clock.advance(days=7, seconds=1)

    response = await client.post("/api/auth/refresh", headers=ORIGIN)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


async def test_me_requires_a_valid_bearer_token(client: AsyncClient) -> None:
    missing = await client.get("/api/me")
    garbage = await client.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"})

    for response in (missing, garbage):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_required"


async def test_refresh_requires_a_session_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/auth/refresh", headers=ORIGIN)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


async def test_refresh_and_logout_reject_a_foreign_origin(client: AsyncClient) -> None:
    logged_in = await register_and_login(client)

    bad_origin = {"Origin": "https://evil.example"}
    refresh = await client.post("/api/auth/refresh", headers=bad_origin)
    assert refresh.status_code == 403
    assert refresh.json()["error"]["code"] == "session_invalid"

    logout = await client.post("/api/auth/logout", headers=bad_origin)
    assert logout.status_code == 403
    assert logout.json()["error"]["code"] == "session_invalid"

    # The rejected logout did not revoke anything.
    good = await client.post("/api/auth/refresh", headers=ORIGIN)
    assert good.status_code == 200
    assert (await client.get("/api/me", headers=bearer(logged_in))).status_code == 200
