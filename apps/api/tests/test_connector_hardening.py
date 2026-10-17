"""Connector retry, OAuth refresh errors and per-connection health. Offline: urlopen and sleep are faked."""
import email.message
import io
import urllib.error

import pytest

from app.connectors import base
from app.connectors.oauth import OAuthError
from app.connectors.registry import connection_health


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _err(code, retry_after=None):
    msg = email.message.Message()
    if retry_after:
        msg["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://api.example.test/x", code, "err", msg, None)


def _script(monkeypatch, outcomes):
    calls, waits = [], []

    def fake_urlopen(req, timeout=None):
        calls.append(req.get_method())
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return _Resp(o)

    monkeypatch.setattr(base.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(base.time, "sleep", waits.append)
    return calls, waits


def test_429_is_retried_and_honours_retry_after(monkeypatch):
    calls, waits = _script(monkeypatch, [_err(429, "3"), b"ok"])
    assert base.default_http("https://api.example.test/x", {}) == b"ok"
    assert len(calls) == 2 and waits == [3.0]


def test_read_503_backs_off_then_gives_up(monkeypatch):
    calls, waits = _script(monkeypatch, [_err(503), _err(503), _err(503), _err(503)])
    with pytest.raises(urllib.error.HTTPError):
        base.default_http("https://api.example.test/x", {})
    assert len(calls) == base.MAX_ATTEMPTS and waits == [1.0, 2.0, 4.0]


def test_write_5xx_is_not_retried(monkeypatch):
    calls, waits = _script(monkeypatch, [_err(503)])
    with pytest.raises(urllib.error.HTTPError):
        base.default_http("https://api.example.test/x", {"X-Method": "PATCH", "X-Post-Body": "{}"})
    assert calls == ["PATCH"] and waits == []


def test_non_retryable_error_raises_at_once(monkeypatch):
    calls, waits = _script(monkeypatch, [_err(404)])
    with pytest.raises(urllib.error.HTTPError):
        base.default_http("https://api.example.test/x", {})
    assert len(calls) == 1 and waits == []


def test_refresh_failure_says_reconnect(monkeypatch):
    from app import main as m

    class Row:
        connector = "gmail"
        token_sealed = "x"

    monkeypatch.setattr(m.oauth, "config_for", lambda name: None)
    monkeypatch.setattr(m.vault, "unseal", lambda s: "rt")

    def refused(cfg, token, http):
        raise OAuthError("token endpoint refused: invalid_grant")

    monkeypatch.setattr(m.oauth, "refresh", refused)
    with pytest.raises(base.ConnectorError, match="reconnect the account"):
        m._oauth_access_token(Row())


class _Row:
    def __init__(self, last_run=None, last_status=None):
        self.last_run, self.last_status = last_run, last_status


def test_health_states():
    assert connection_health(_Row())["health"] == "never_run"
    assert connection_health(_Row("2026-10-17T10:00:00Z", "ok: 3 new, 1 unchanged"))["health"] == "ok"
    e = connection_health(_Row("2026-10-17T10:00:00Z", "error: token refresh failed"))
    assert e["health"] == "error" and e["detail"] == "error: token refresh failed"
