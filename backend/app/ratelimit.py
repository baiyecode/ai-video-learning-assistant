"""In-memory, Clock-based rate limiting for public entry points.

Each scope has a fixed policy (``limit`` hits per sliding ``window``). State lives in
this process only; a restart resets it, which is acceptable for the single-VPS P1
deployment (ADR-0001). Time comes from the injected ``Clock`` so tests and quota
windows stay deterministic.

Rejections are ``429 too_many_requests`` with a ``Retry-After`` header and
``details: {scope, retry_after, reset_at}``; ``reset_at`` is the instant the oldest
hit leaves the window, i.e. when a retry can succeed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Settings
from .errors import AppError, ErrorCode
from .ports import Clock

MESSAGE_TOO_MANY = "请求过于频繁，请 {retry_after} 秒后再试"


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    scope: str
    limit: int
    window_seconds: float
    message: str = MESSAGE_TOO_MANY


def build_rules(settings: Settings) -> dict[str, RateLimitRule]:
    """Per-scope policies from configuration. ``limit <= 0`` disables the scope."""
    return {
        "videos.resolve": RateLimitRule(
            "videos.resolve",
            settings.rate_limit_resolve_per_minute,
            60.0,
            "视频解析请求过于频繁，请 {retry_after} 秒后再试",
        ),
        "downloads.create": RateLimitRule(
            "downloads.create",
            settings.rate_limit_download_per_minute,
            60.0,
            "下载请求过于频繁，请 {retry_after} 秒后再试",
        ),
        "auth.login": RateLimitRule(
            "auth.login",
            settings.rate_limit_login_per_15_minutes,
            15 * 60.0,
            "登录尝试过于频繁，请 {retry_after} 秒后再试",
        ),
        "auth.register": RateLimitRule(
            "auth.register",
            settings.rate_limit_register_per_hour,
            60 * 60.0,
            "注册请求过于频繁，请 {retry_after} 秒后再试",
        ),
        "analyses.create": RateLimitRule(
            "analyses.create",
            int(settings.rate_limit_analysis_seconds > 0),
            settings.rate_limit_analysis_seconds,
            "AI 分析请求过于频繁，请 {retry_after} 秒后再试",
        ),
        "reports.create": RateLimitRule(
            "reports.create",
            settings.rate_limit_report_per_hour,
            60 * 60.0,
            "举报提交过于频繁，请 {retry_after} 秒后再试",
        ),
    }


class RateLimiter:
    """Sliding-window counters keyed by ``(scope, key)``.

    ``hit`` is check-and-record for endpoints that always count an attempt.
    ``ensure``/``record`` are split where only a successful outcome should count
    (Analysis creation: reusing an existing Analysis must stay free).
    """

    def __init__(self, clock: Clock, rules: dict[str, RateLimitRule] | None = None) -> None:
        self._clock = clock
        self._rules = rules or {}
        self._hits: dict[tuple[str, str], list[datetime]] = {}
        # Last "tag" (e.g. Video id) recorded per key, used to keep idempotent
        # retries (same Video) outside the new-Analysis throttle.
        self._last_tag: dict[tuple[str, str], str] = {}

    def rule(self, scope: str) -> RateLimitRule:
        return self._rules[scope]

    def hit(self, scope: str, key: str | None) -> None:
        self.ensure(scope, key)
        self.record(scope, key)

    def ensure(self, scope: str, key: str | None) -> None:
        """Raise ``too_many_requests`` when the key is already at its limit."""
        rule = self._rules[scope]
        if rule.limit <= 0 or rule.window_seconds <= 0:
            return
        now = self._clock.now()
        hits = self._recent(rule, key, now)
        if len(hits) < rule.limit:
            return

        reset_at = hits[0] + timedelta(seconds=rule.window_seconds)
        retry_after = max(1, math.ceil((reset_at - now).total_seconds()))
        raise AppError(
            429,
            ErrorCode.TOO_MANY_REQUESTS,
            rule.message.format(retry_after=retry_after),
            {
                "scope": scope,
                "retry_after": retry_after,
                "reset_at": reset_at.isoformat(),
            },
            headers={"Retry-After": str(retry_after)},
        )

    def record(self, scope: str, key: str | None, *, tag: str | None = None) -> None:
        rule = self._rules[scope]
        if rule.limit <= 0 or rule.window_seconds <= 0:
            return
        now = self._clock.now()
        hits = self._recent(rule, key, now)
        hits.append(now)
        self._hits[(scope, _key(key))] = hits
        if tag is not None:
            self._last_tag[(scope, _key(key))] = tag
        self._prune(now)

    def last_tag(self, scope: str, key: str | None) -> str | None:
        """The tag passed to the most recent ``record`` for this key, if any."""
        return self._last_tag.get((scope, _key(key)))

    def reset(self) -> None:
        self._hits.clear()
        self._last_tag.clear()

    @property
    def tracked_keys(self) -> int:
        """Number of live ``(scope, key)`` entries (diagnostics and tests)."""
        return len(self._hits)

    def _prune(self, now: datetime) -> None:
        """Drop keys whose whole window has elapsed so memory stays bounded."""
        for (scope, key), hits in list(self._hits.items()):
            rule = self._rules.get(scope)
            if rule is None:
                continue
            cutoff = now - timedelta(seconds=rule.window_seconds)
            fresh = [hit for hit in hits if hit > cutoff]
            if fresh:
                self._hits[(scope, key)] = fresh
            else:
                del self._hits[(scope, key)]
                self._last_tag.pop((scope, key), None)

    def _recent(
        self, rule: RateLimitRule, key: str | None, now: datetime
    ) -> list[datetime]:
        cutoff = now - timedelta(seconds=rule.window_seconds)
        hits = [hit for hit in self._hits.get((rule.scope, _key(key)), ()) if hit > cutoff]
        self._hits[(rule.scope, _key(key))] = hits
        return hits


def _key(key: str | None) -> str:
    return key or "unknown"
