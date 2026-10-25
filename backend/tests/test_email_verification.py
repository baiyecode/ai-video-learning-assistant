"""Email verification (tickets #21 & #22): issuance, confirmation, resend, Analysis gate.

Everything is exercised through the in-process HTTP seam with fake adapters and a
FrozenClock. The observable surface is the in-memory inbox (``adapters.email_sender``),
HTTP status codes, the unified error envelope and the ``/api/me`` representation.

Registration no longer authenticates, so any test that needs a Session logs in; any test
that needs a *verified* Account confirms the delivered token first.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from app.adapters.smtp_email import SmtpEmailSender
from app.config import Settings
from app.container import Adapters, build_production_adapters
from app.errors import AppError
from app.main import create_app
from app.ports import OutboundEmail
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from tests.auth_flows import bearer
from tests.fakes import FakeEmailSender, make_fake_adapters, sample_video

ORIGIN = {"Origin": "http://testserver"}
PASSWORD = "correct-horse"
_TOKEN_IN_LINK = re.compile(r"token=([A-Za-z0-9_\-]+)")


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


async def login(client: AsyncClient, *, email: str = "learner@example.com") -> Any:
    response = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response


def sent_emails(adapters: Adapters) -> list[Any]:
    return adapters.email_sender.sent  # type: ignore[attr-defined]


def verification_token(adapters: Adapters, index: int = 0) -> str:
    """Extract the one-time token from the verification link of a delivered email."""
    match = _TOKEN_IN_LINK.search(sent_emails(adapters)[index].body)
    assert match is not None, "no verification token in the delivered email"
    return match.group(1)


async def confirm(client: AsyncClient, token: str) -> Any:
    return await client.post("/api/auth/verification/confirm", json={"token": token})


async def _resolve_video(client: AsyncClient, adapters: Adapters, key: str = "gatevid0001") -> str:
    url = f"https://www.youtube.com/watch?v={key}"
    adapters.video_source.videos[url] = sample_video(platform_video_id=key)  # type: ignore[attr-defined]
    response = await client.post("/api/videos/resolve", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["video"]["id"]


# --------------------------------------------------------------------------- #
# Issuance & confirmation (ticket #21)
# --------------------------------------------------------------------------- #


async def test_register_delivers_one_verification_email_with_a_return_link(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client, email="Learner@Example.com")

    inbox = sent_emails(adapters)
    assert len(inbox) == 1
    message = inbox[0]
    assert message.to == "learner@example.com"
    assert message.subject
    assert verification_token(adapters)
    assert "/verify-email?token=" in message.body


async def test_a_verification_email_is_sent_only_once_even_across_logins(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client)
    await login(client)
    await client.post("/api/auth/logout", headers=ORIGIN)
    await login(client)

    assert len(sent_emails(adapters)) == 1


async def test_new_account_is_unverified_until_the_link_is_confirmed(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client)
    logged_in = await login(client)

    before = await client.get("/api/me", headers=bearer(logged_in))
    assert before.status_code == 200, before.text
    assert before.json()["account"]["email_verified_at"] is None

    confirmed = await confirm(client, verification_token(adapters))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email"] == "learner@example.com"
    assert confirmed.json()["email_verified_at"] == "2026-01-15T08:00:00+00:00"

    after = await client.get("/api/me", headers=bearer(logged_in))
    assert after.json()["account"]["email_verified_at"] == "2026-01-15T08:00:00+00:00"


async def test_confirm_rejects_an_unknown_token(client: AsyncClient) -> None:
    response = await confirm(client, "bogus")

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "verification_token_invalid"


async def test_confirm_hits_a_frequency_limit_per_client(
    client: AsyncClient, settings: Settings
) -> None:
    """Story 26: link hits are throttled too, not just mail sends.

    The dedicated ``auth.verification.confirm`` scope bounds token-guessing bursts
    per client: every earlier attempt still reads as the neutral invalid-token 400,
    and once the ceiling is reached the endpoint answers 429 like the other scopes.
    """
    ceiling = settings.rate_limit_verification_confirm_per_hour
    for attempt in range(ceiling):
        response = await confirm(client, f"guess-{attempt}")
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "verification_token_invalid"

    limited = await confirm(client, "one-guess-too-many")
    assert limited.status_code == 429, limited.text
    error = limited.json()["error"]
    assert error["code"] == "too_many_requests"
    assert error["details"]["scope"] == "auth.verification.confirm"


async def test_taken_email_registration_burns_the_same_bcrypt_work(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 22 timing side channel: a taken email must cost what a new one costs.

    The new-Account path's only bcrypt work is hashing the submitted password; the
    taken-email path used to answer instantly, leaking existence by timing. It now
    runs the login path's dummy-hash equalizer first. Observed through the bcrypt
    ``verify_password`` seam (not wall-clock): exactly one verification against the
    module's fixed dummy hash, with the submitted password.
    """
    from app.modules.identity import security

    checks: list[tuple[str, str]] = []

    def _spy(password: str, password_hash: str) -> bool:
        checks.append((password, password_hash))
        return False

    monkeypatch.setattr(security, "verify_password", _spy)

    await register(client, email="taken@example.com")  # the new-Account path: hash only
    assert checks == []

    response = await register(client, email="taken@example.com")
    assert response.status_code == 201, response.text
    assert checks == [("correct-horse", security._DUMMY_PASSWORD_HASH)]


async def test_a_verified_token_cannot_be_reused(client: AsyncClient, adapters: Adapters) -> None:
    await register(client)
    token = verification_token(adapters)

    first = await confirm(client, token)
    assert first.status_code == 200, first.text

    replay = await confirm(client, token)
    assert replay.status_code == 400, replay.text
    assert replay.json()["error"]["code"] == "verification_token_invalid"


async def test_expired_token_is_rejected_with_a_resend_hint(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client)
    # Default TTL is 24h from issue (2026-01-15T08:00Z); step just past it.
    adapters.clock.advance(days=1, seconds=1)  # type: ignore[attr-defined]

    response = await confirm(client, verification_token(adapters))

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "verification_token_expired"
    assert "已过期，请重新发送" in error["message"]

    logged_in = await login(client)
    me = await client.get("/api/me", headers=bearer(logged_in))
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

            response = await confirm(client, verification_token(adapters))

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "verification_token_expired"


async def test_password_change_invalidates_an_unused_verification_token(
    client: AsyncClient, adapters: Adapters
) -> None:
    logged_in = bearer(await login_after_register(client))
    token = verification_token(adapters)

    changed = await client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "new-correct-horse"},
        headers=logged_in,
    )
    assert changed.status_code == 204, changed.text

    confirm_response = await confirm(client, token)
    assert confirm_response.status_code == 400, confirm_response.text
    assert confirm_response.json()["error"]["code"] == "verification_token_invalid"

    # The new password is the one that works now.
    login2 = await client.post(
        "/api/auth/login",
        json={"email": "learner@example.com", "password": "new-correct-horse"},
    )
    assert login2.status_code == 200, login2.text


async def login_after_register(client: AsyncClient) -> Any:
    await register(client)
    return await login(client)


async def test_password_change_rejects_wrong_current_and_weak_new_password(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = bearer(await login_after_register(client))

    wrong_current = await client.post(
        "/api/auth/password",
        json={"current_password": "not-my-password", "new_password": "new-correct-horse"},
        headers=headers,
    )
    assert wrong_current.status_code == 403, wrong_current.text
    assert wrong_current.json()["error"]["code"] == "invalid_credentials"

    weak_new = await client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=headers,
    )
    assert weak_new.status_code == 400, weak_new.text
    assert weak_new.json()["error"]["code"] == "weak_password"

    # A rejected change keeps the verification token usable.
    still_usable = await confirm(client, verification_token(adapters))
    assert still_usable.status_code == 200, still_usable.text


# --------------------------------------------------------------------------- #
# Registration does not leak that an email is taken (ticket #22)
# --------------------------------------------------------------------------- #


async def test_taken_email_gets_a_reminder_and_creates_no_second_account(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client, email="learner@example.com")
    taken = await register(client, email="Learner@Example.com")

    assert taken.status_code == 201, taken.text
    inbox = sent_emails(adapters)
    assert len(inbox) == 2
    reminder = inbox[1]
    assert reminder.to == "learner@example.com"
    # The reminder never exposes a verification link (which would confirm the account).
    assert "/verify-email?token=" not in reminder.body

    # Only one Account exists: the original password still logs in exactly once.
    logged_in = await login(client, email="learner@example.com")
    assert logged_in.status_code == 200, logged_in.text


async def test_registration_survives_a_failed_email_delivery(settings: Settings) -> None:
    """Ticket #43: the outage is visible (503), yet the Account stands and recovers.

    Registration claims 请查收邮箱中的验证邮件, so a mail that never left must not
    answer 201. The committed Account is untouched by the failure - login works, and
    once the mail service is back the resend endpoint delivers the verification link.
    """
    adapters = make_fake_adapters(
        email_sender=FakeEmailSender(fail_with=RuntimeError("smtp is down"))
    )
    app = create_app(settings=settings, adapters=adapters)

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={"email": "learner@example.com", "password": PASSWORD},
            )
            assert response.status_code == 503, response.text
            error = response.json()["error"]
            assert error["code"] == "service_unavailable"
            assert error["message"] == "邮件发送失败，请稍后重试"
            assert adapters.email_sender.sent == []

            # The registration itself survived: the password still logs in (story 19).
            logged_in = await client.post(
                "/api/auth/login",
                json={"email": "learner@example.com", "password": PASSWORD},
            )
            assert logged_in.status_code == 200, logged_in.text

            # Recovery: with the mail service back, the resend delivers the link.
            adapters.email_sender.fail_with = None
            resent = await client.post(
                "/api/auth/verification/request",
                headers=bearer(logged_in),
            )
            assert resent.status_code == 202, resent.text
            assert len(adapters.email_sender.sent) == 1


async def test_smtp_adapter_refuses_to_send_without_configuration(settings: Settings) -> None:
    sender = SmtpEmailSender(settings)

    with pytest.raises(AppError) as raised:
        await sender.send(OutboundEmail(to="someone@example.com", subject="s", body="b"))

    assert raised.value.status == 503
    assert raised.value.code == "service_unavailable"
    assert "邮件服务未配置" in raised.value.message


async def test_fake_adapters_mode_ships_an_observable_inbox(settings: Settings) -> None:
    tuned = settings.model_copy(update={"fake_adapters": True})
    adapters = build_production_adapters(tuned)

    await adapters.email_sender.send(OutboundEmail(to="someone@example.com", subject="s", body="b"))

    assert [
        message.to for message in adapters.email_sender.sent  # type: ignore[attr-defined]
    ] == ["someone@example.com"]


# --------------------------------------------------------------------------- #
# Resend endpoint: POST /auth/verification/request (ticket #22)
# --------------------------------------------------------------------------- #


async def test_resend_requires_a_login(client: AsyncClient) -> None:
    response = await client.post("/api/auth/verification/request")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "auth_required"


async def test_resend_issues_a_fresh_token_and_delivers_another_email(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = bearer(await login_after_register(client))
    old_token = verification_token(adapters)

    resent = await client.post("/api/auth/verification/request", headers=headers)
    assert resent.status_code == 202, resent.text
    assert resent.json()["email_verified"] is False
    assert len(sent_emails(adapters)) == 2

    new_token = verification_token(adapters, index=1)
    assert new_token != old_token
    # Resend rotates the single active token: the previous link is dead.
    stale = await confirm(client, old_token)
    assert stale.status_code == 400, stale.text
    assert stale.json()["error"]["code"] == "verification_token_invalid"

    fresh = await confirm(client, new_token)
    assert fresh.status_code == 200, fresh.text


async def test_resend_to_an_already_verified_email_sends_nothing(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = bearer(await login_after_register(client))
    await confirm(client, verification_token(adapters))

    resent = await client.post("/api/auth/verification/request", headers=headers)
    assert resent.status_code == 202, resent.text
    body = resent.json()
    assert body["email_verified"] is True
    # No additional mail was delivered; the verified state is untouched.
    assert len(sent_emails(adapters)) == 1

    me = await client.get("/api/me", headers=headers)
    assert me.json()["account"]["email_verified_at"] == "2026-01-15T08:00:00+00:00"


async def test_resend_is_rate_limited_and_reports_a_retry_time(
    client: AsyncClient, adapters: Adapters, settings: Settings
) -> None:
    headers = bearer(await login_after_register(client))
    limit = settings.rate_limit_verification_request_per_hour
    for _ in range(limit):
        allowed = await client.post("/api/auth/verification/request", headers=headers)
        assert allowed.status_code == 202, allowed.text

    rejected = await client.post("/api/auth/verification/request", headers=headers)
    assert rejected.status_code == 429, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "too_many_requests"
    assert error["details"]["scope"] == "auth.verification.request"
    assert error["details"]["retry_after"] > 0
    assert int(rejected.headers["retry-after"]) == error["details"]["retry_after"]


async def test_resend_reports_a_failed_email_delivery(
    client: AsyncClient, adapters: Adapters
) -> None:
    """Story 21 (ticket #43): an outage must not lie with the 已发送 ack.

    The resend answer is a delivery claim, so it may only appear once the mail has
    actually left. With the fake inbox raising, the caller gets the unified error
    envelope - 503 ``service_unavailable`` with the retry sentence - and no extra
    mail is fabricated in the inbox.
    """
    headers = bearer(await login_after_register(client))
    adapters.email_sender.fail_with = RuntimeError("smtp is down")  # type: ignore[attr-defined]

    resent = await client.post("/api/auth/verification/request", headers=headers)

    assert resent.status_code == 503, resent.text
    error = resent.json()["error"]
    assert error["code"] == "service_unavailable"
    assert error["message"] == "邮件发送失败，请稍后重试"
    assert "已发送" not in error["message"]
    # Only the registration mail was delivered; the failed resend sent nothing.
    assert len(sent_emails(adapters)) == 1


async def test_resend_recovers_after_a_failed_delivery(client: AsyncClient, adapters: Adapters) -> None:
    """The 503 is retryable: clearing the outage lets the resend actually deliver."""
    headers = bearer(await login_after_register(client))
    adapters.email_sender.fail_with = RuntimeError("smtp is down")  # type: ignore[attr-defined]
    failed = await client.post("/api/auth/verification/request", headers=headers)
    assert failed.status_code == 503, failed.text

    adapters.email_sender.fail_with = None  # type: ignore[attr-defined]
    resent = await client.post("/api/auth/verification/request", headers=headers)

    assert resent.status_code == 202, resent.text
    assert resent.json()["message"] == "验证邮件已发送，请查收邮箱"
    assert len(sent_emails(adapters)) == 2


# --------------------------------------------------------------------------- #
# Analysis is gated on a verified email, without consuming Quota (ticket #22)
# --------------------------------------------------------------------------- #


async def test_unverified_email_cannot_create_an_analysis_and_spends_no_quota(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = bearer(await login_after_register(client))
    video_id = await _resolve_video(client, adapters)

    rejected = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert rejected.status_code == 403, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "email_not_verified"
    assert "请先验证邮箱" in error["message"]

    me = await client.get("/api/me", headers=headers)
    assert me.json()["quota"] == {
        "daily_limit": 3,
        "used": 0,
        "remaining": 3,
        "resets_at": "2026-01-16T00:00:00+08:00",
        "membership": "free",
    }


async def test_verifying_the_email_unblocks_analysis_creation(
    client: AsyncClient, adapters: Adapters
) -> None:
    headers = bearer(await login_after_register(client))
    video_id = await _resolve_video(client, adapters, "gatevid0002")

    blocked = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert blocked.status_code == 403, blocked.text

    await confirm(client, verification_token(adapters))

    created = await client.post("/api/analyses", json={"video_id": video_id}, headers=headers)
    assert created.status_code == 201, created.text
    me = await client.get("/api/me", headers=headers)
    assert me.json()["quota"]["used"] == 1


async def test_verification_does_not_gate_login_resolve_subtitle_or_download(
    client: AsyncClient, adapters: Adapters
) -> None:
    await register(client, email="passive@example.com")
    # Resolve and download are visitor-allowed; login works unverified.
    url = "https://www.youtube.com/watch?v=gatevid0003"
    adapters.video_source.videos[url] = sample_video(platform_video_id="gatevid0003")  # type: ignore[attr-defined]
    resolved = await client.post("/api/videos/resolve", json={"url": url})
    assert resolved.status_code == 200, resolved.text
    video_id = resolved.json()["video"]["id"]

    logged_in = await login(client, email="passive@example.com")
    assert logged_in.status_code == 200, logged_in.text
    headers = bearer(logged_in)

    subtitle = await client.get(f"/api/videos/{video_id}/subtitles?format=txt", headers=headers)
    assert subtitle.status_code == 200, subtitle.text

    download = await client.post(
        "/api/downloads", json={"video_id": video_id, "format_id": "bestaudio"}, headers=headers
    )
    assert download.status_code == 202, download.text
