"""HMAC-signed temporary file URLs.

A signed URL carries only ``download_id``, an absolute expiry instant and an
HMAC-SHA256 signature over both. Filesystem paths never leave the server. The
signature is compared in constant time so a 403 cannot be used as a timing oracle.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

from app.errors import AppError, ErrorCode

SIGNED_URL_TTL = timedelta(minutes=15)
FILE_TTL = timedelta(hours=1)

_MESSAGE_INVALID_SIGNATURE = "下载链接无效，请刷新页面后重试"
_MESSAGE_LINK_EXPIRED = "下载链接已过期，请刷新页面重新获取"


def signature_for(download_id: str, expires_at: int, secret: str) -> str:
    """Hex HMAC-SHA256 over ``download:<id>:<unix expiry>``."""
    payload = f"download:{download_id}:{expires_at}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def signed_file_path(download_id: str, expires_at: int, secret: str) -> str:
    """API path (same origin) for the signed file download."""
    signature = signature_for(download_id, expires_at, secret)
    return f"/api/downloads/{download_id}/file?expires={expires_at}&sig={signature}"


def verify_signature(
    *,
    download_id: str,
    expires_at: int,
    signature: str,
    secret: str,
    now: datetime,
) -> None:
    """Raise ``invalid_signature`` for a forged link and ``file_expired`` once it lapses."""
    expected = signature_for(download_id, expires_at, secret)
    if not signature or not hmac.compare_digest(expected, signature):
        raise AppError(403, ErrorCode.INVALID_SIGNATURE, _MESSAGE_INVALID_SIGNATURE)
    if expires_at <= int(now.timestamp()):
        raise AppError(403, ErrorCode.FILE_EXPIRED, _MESSAGE_LINK_EXPIRED)
