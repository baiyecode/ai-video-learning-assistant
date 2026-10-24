"""Email verification lifecycle helpers (part of the Account lifecycle, ticket #21).

A register mints a one-time opaque token; only its SHA-256 hash and an expiry instant
are persisted on the Account. The raw token travels exclusively inside the
verification link of the delivered email. Confirmation and invalidation clear the pair.
"""

from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.modules.identity.models import Account
from app.modules.identity.security import hash_verification_token, new_verification_token
from app.ports import Clock, OutboundEmail

# Frontend page that receives ``?token=`` and calls ``POST /api/auth/verification/confirm``.
FRONTEND_VERIFY_PATH = "/verify-email"

SUBJECT = "请验证你的邮箱地址"


def issue_verification_token(account: Account, settings: Settings, clock: Clock) -> str:
    """Attach a fresh one-time token to the Account and return the raw token for the email."""
    raw_token = new_verification_token()
    account.verification_token_hash = hash_verification_token(raw_token)
    account.verification_expires_at = clock.now() + timedelta(
        hours=settings.email_verification_token_ttl_hours
    )
    return raw_token


def build_verification_link(settings: Settings, raw_token: str) -> str:
    base = settings.frontend_base_url.rstrip("/")
    return f"{base}{FRONTEND_VERIFY_PATH}?token={raw_token}"


def verification_email(account: Account, settings: Settings, raw_token: str) -> OutboundEmail:
    link = build_verification_link(settings, raw_token)
    ttl_hours = settings.email_verification_token_ttl_hours
    body = (
        f"你好，\n\n"
        f"欢迎使用{settings.app_name}。请在 {ttl_hours} 小时内点击下方链接完成邮箱验证：\n\n"
        f"{link}\n\n"
        f"验证链接仅可使用一次。如果这不是你本人的操作，请忽略本邮件。"
    )
    return OutboundEmail(to=account.email, subject=SUBJECT, body=body)


REMINDER_SUBJECT = "有人使用你的邮箱注册"


def reminder_email(email: str, settings: Settings) -> OutboundEmail:
    """Copy for an already-occupied email: never reveals the account state (story 22).

    It goes to the address that was just offered at registration, telling the owner
    someone tried to sign up with it and what to do if that was them, without exposing
    whether an account exists or whether its email is already verified.
    """
    body = (
        f"你好，\n\n"
        f"有人刚刚使用这个邮箱在{settings.app_name}尝试注册。\n\n"
        f"如果这是你本人的操作，说明你的账号尚未完成邮箱验证或你想重新发起：请前往登录页重新登录，"
        f"并在验证邮件中完成验证。\n\n"
        f"如果这不是你本人的操作，请忽略本邮件，你的账号不受影响。"
    )
    return OutboundEmail(to=email, subject=REMINDER_SUBJECT, body=body)
