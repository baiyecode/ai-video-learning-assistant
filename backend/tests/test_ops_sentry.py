from __future__ import annotations

import pytest
from app.logging_setup import request_id_var
from app.modules.ops.sentry import init_sentry, tag_request_id

sentry_sdk = pytest.importorskip("sentry_sdk")


def test_sentry_is_a_noop_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    assert init_sentry(environment="test") is False
    assert calls == []


def test_sentry_initialises_when_a_dsn_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    dsn = "https://public@example.invalid/42"

    assert init_sentry(dsn=dsn, environment="test", traces_sample_rate=0.25) is True

    assert calls[0]["dsn"] == dsn
    assert calls[0]["environment"] == "test"
    assert calls[0]["traces_sample_rate"] == 0.25
    assert calls[0]["before_send"] is tag_request_id


def test_sentry_dsn_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/7")

    assert init_sentry(environment="test") is True
    assert calls[0]["dsn"] == "https://public@example.invalid/7"


def test_a_broken_sentry_init_never_blocks_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(**kwargs: object) -> None:
        raise ValueError("bad dsn")

    monkeypatch.setattr(sentry_sdk, "init", explode)

    assert init_sentry(dsn="not-a-dsn", environment="test") is False


def test_events_are_tagged_with_the_current_request_id() -> None:
    token = request_id_var.set("req-9f8e")
    try:
        event = tag_request_id({"tags": {}}, {})
    finally:
        request_id_var.reset(token)

    assert event["tags"]["request_id"] == "req-9f8e"


def test_events_outside_a_request_are_left_untagged() -> None:
    token = request_id_var.set("")
    try:
        event = tag_request_id({}, {})
    finally:
        request_id_var.reset(token)

    assert "tags" not in event
