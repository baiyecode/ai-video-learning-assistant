"""Unified error envelope.

Every failure exits as::

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

Messages are user-facing (Simplified Chinese); codes are the stable contract.
Stack traces are logged server-side and never returned to clients.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from .logging_setup import request_id_var

logger = logging.getLogger("app.errors")


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_URL = "unsupported_url"
    PLAYLIST_NOT_SUPPORTED = "playlist_not_supported"
    DRM_PROTECTED = "drm_protected"
    MEMBERS_ONLY = "members_only"
    VIDEO_UNAVAILABLE = "video_unavailable"
    RESOLVE_FAILED = "resolve_failed"
    VIDEO_NOT_FOUND = "video_not_found"
    FORMATS_EXPIRED = "formats_expired"
    SUBTITLES_UNAVAILABLE = "subtitles_unavailable"
    DOWNLOAD_NOT_FOUND = "download_not_found"
    DOWNLOAD_NOT_READY = "download_not_ready"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_LIMIT_REACHED = "download_limit_reached"
    DOWNLOAD_TOO_LONG = "download_too_long"
    DOWNLOAD_TOO_LARGE = "download_too_large"
    FILE_EXPIRED = "file_expired"
    INVALID_SIGNATURE = "invalid_signature"
    TOO_MANY_REQUESTS = "too_many_requests"
    BUDGET_EXHAUSTED = "budget_exhausted"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH_REQUIRED = "auth_required"
    INVALID_CREDENTIALS = "invalid_credentials"
    EMAIL_TAKEN = "email_taken"
    WEAK_PASSWORD = "weak_password"
    SESSION_INVALID = "session_invalid"
    ANALYSIS_NOT_FOUND = "analysis_not_found"
    ANALYSIS_FAILED = "analysis_failed"
    REPORT_INVALID = "report_invalid"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    # Generic framework-level codes.
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    FORBIDDEN = "forbidden"


class AppError(Exception):
    """Business failure. ``status`` is the HTTP status, ``code`` the stable contract code."""

    def __init__(
        self,
        status: int,
        code: str | ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code.value if isinstance(code, ErrorCode) else str(code)
        self.message = message
        self.details = details or {}


def request_id_of(request: Request | None = None) -> str:
    if request is not None:
        rid = getattr(request.state, "request_id", None)
        if rid:
            return str(rid)
    return request_id_var.get()


def error_body(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def _json_error(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None,
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=error_body(code=code, message=message, details=details, request_id=request_id),
        headers={"X-Request-ID": request_id} if request_id else None,
    )


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    request_id = request_id_of(request)
    log = logger.error if exc.status >= 500 else logger.warning
    log(
        "app_error",
        extra={"event": "app_error", "code": exc.code, "status_code": exc.status},
        exc_info=exc if exc.status >= 500 else None,
    )
    return _json_error(exc.status, exc.code, exc.message, exc.details, request_id)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _json_error(
        422,
        ErrorCode.INVALID_REQUEST.value,
        "请求参数有误",
        {"errors": jsonable_encoder(exc.errors())},
        request_id_of(request),
    )


_HTTP_ERROR_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.INVALID_REQUEST,
    413: ErrorCode.INVALID_REQUEST,
    415: ErrorCode.INVALID_REQUEST,
    429: ErrorCode.TOO_MANY_REQUESTS,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}

_HTTP_ERROR_MESSAGES: dict[int, str] = {
    400: "请求无效",
    401: "请先登录",
    403: "没有权限执行该操作",
    404: "请求的资源不存在",
    405: "不支持该请求方法",
    409: "请求与当前状态冲突",
    413: "请求内容过大",
    415: "不支持的请求格式",
    429: "请求过于频繁，请稍后再试",
    503: "服务暂时不可用，请稍后再试",
}

_FRAMEWORK_DEFAULT_DETAILS = {"Not Found", "Method Not Allowed", "Bad Request", "Unauthorized"}


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_ERROR_CODES.get(exc.status_code, ErrorCode.INVALID_REQUEST)
    message = _HTTP_ERROR_MESSAGES.get(exc.status_code, "请求失败")
    details: dict[str, Any] = {}
    if exc.detail and exc.detail not in _FRAMEWORK_DEFAULT_DETAILS:
        details["detail"] = exc.detail
    return _json_error(exc.status_code, code.value, message, details, request_id_of(request))


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_of(request)
    logger.error(
        "unhandled_exception",
        extra={"event": "unhandled_exception", "code": ErrorCode.INTERNAL_ERROR.value},
        exc_info=exc,
    )
    return _json_error(
        500,
        ErrorCode.INTERNAL_ERROR.value,
        "服务器内部错误，请稍后重试",
        {},
        request_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    # Starlette routes this through ServerErrorMiddleware, so it also covers middleware errors.
    app.add_exception_handler(Exception, _handle_unexpected_error)
