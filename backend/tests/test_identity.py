"""Account registration, login, Session refresh/logout and ``/api/me``.

Everything is exercised through the in-process HTTP seam with fake adapters and a
FrozenClock, so token/session expiry is deterministic.
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
    email: str = "Learner@Example.com",
    password: str = PASSWORD,
    expect: int = 201,
) -> Any:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == expect, response.text
    return response


async def test_register_login_and_me_round_trip(client: AsyncClient) -> None:
    response = await register(client)

    body = response.json()
    assert body["account"]["email"] == "learner@example.com"
    assert body["account"]["id"]
    assert body["account"]["created_at"]
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
    assert me.json()["quota"] is None

    # Email is normalised, so logging in with different casing works.
    login = await client.post(
        "/api/auth/login", json={"email": "LEARNER@example.COM", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["account"]["id"] == body["account"]["id"]

    me = await client.get("/api/me", headers=bearer(login))
    assert me.status_code == 200


async def test_duplicate_email_is_rejected_case_insensitively(client: AsyncClient) -> None:
    await register(client, email="learner@example.com")

    response = await register(client, email="Learner@Example.com", expect=409)

    assert response.json()["error"]["code"] == "email_taken"


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

    wrong_password = await client.post(
        "/api/auth/login", json={"email": "learner@example.com", "password": "wrong-password"}
    )
    unknown_email = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


async def test_refresh_rotates_the_token_and_rejects_the_old_one(client: AsyncClient) -> None:
    registered = await register(client)
    old_refresh = client.cookies.get("refresh_token")
    assert old_refresh

    refreshed = await client.post("/api/auth/refresh", headers=ORIGIN)
    assert refreshed.status_code == 200
    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh
    assert refreshed.json()["access_token"] != registered.json()["access_token"]
    assert refreshed.json()["account"]["email"] == "learner@example.com"

    me = await client.get("/api/me", headers=bearer(refreshed))
    assert me.status_code == 200

    reused = await client.post(
        "/api/auth/refresh", headers={**ORIGIN, "Cookie": f"refresh_token={old_refresh}"}
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "session_invalid"


async def test_logout_revokes_only_the_current_session(client: AsyncClient) -> None:
    first = await register(client)
    first_refresh = client.cookies.get("refresh_token")
    assert first_refresh

    second = await client.post(
        "/api/auth/login", json={"email": "learner@example.com", "password": PASSWORD}
    )
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
    response = await register(client)
    adapters.clock.advance(seconds=15 * 60 + 1)

    expired = await client.get("/api/me", headers=bearer(response))
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "auth_required"

    refreshed = await client.post("/api/auth/refresh", headers=ORIGIN)
    assert refreshed.status_code == 200
    assert (await client.get("/api/me", headers=bearer(refreshed))).status_code == 200


async def test_expired_refresh_session_is_rejected(client: AsyncClient, adapters: Adapters) -> None:
    await register(client)
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
    registered = await register(client)

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
    assert (await client.get("/api/me", headers=bearer(registered))).status_code == 200
