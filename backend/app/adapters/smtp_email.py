"""Thin SMTP adapter for the EmailSender port (ticket #21).

Keypair/credential enforcement for production deployments is the production-hardening
ticket's job; until then a deployment without ``APP_SMTP_HOST``/``APP_SMTP_FROM`` fails
closed with an understandable 503 instead of crashing at import or startup.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.ports import OutboundEmail

_MESSAGE_EMAIL_UNCONFIGURED = "邮件服务未配置，暂时无法发送邮件"
_MESSAGE_EMAIL_UNAVAILABLE = "邮件服务暂时不可用，请稍后重试"


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: OutboundEmail) -> None:
        if not self._settings.smtp_host or not self._settings.smtp_from:
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_EMAIL_UNCONFIGURED)
        try:
            await asyncio.to_thread(self._send_blocking, message)
        except (OSError, smtplib.SMTPException) as exc:
            raise AppError(503, ErrorCode.SERVICE_UNAVAILABLE, _MESSAGE_EMAIL_UNAVAILABLE) from exc

    def _send_blocking(self, message: OutboundEmail) -> None:
        settings = self._settings
        email = EmailMessage()
        email["From"] = settings.smtp_from
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(email)
