"""Capital IQ and PitchBook adapters. Responses are SYNTHETIC and follow the shape documented in
app/marketvendors.py, which is not verified against the vendors."""
import json

import pytest

from app.marketdata import NoData
from app.marketfeeds import from_env
from app.marketvendors import CapIQProvider, PitchBookProvider

BASE = "https://capiq.example.test/v1"


def doc(*rows):
    return json.dumps({"data": list(rows)}).encode()


def test_capiq_latest_row_and_bearer_auth():
    seen = {}

    def fetch(url, headers):
        seen.update(url=url, auth=headers["Authorization"])
        return doc({"id": "AAPL", "price": 190.5, "currency": "usd", "date": "2026-10-14"},
                   {"id": "AAPL", "price": 191.0, "currency": "usd", "date": "2026-10-15"})
    q = CapIQProvider(base_url=BASE, token="t0k", fetch=fetch).quote("aapl")
    assert (q.price, q.currency, q.as_of, q.source) == (191.0, "USD", "2026-10-15", "capiq")
    assert seen["auth"] == "Bearer t0k" and seen["url"].startswith(BASE + "/prices?")


def test_pitchbook_nodata_and_refuses_http():
    pb = PitchBookProvider(base_url=BASE, token="x", fetch=lambda u, h: doc({"id": "X", "price": None}))
    with pytest.raises(NoData):
        pb.quote("X")
    with pytest.raises(RuntimeError):
        PitchBookProvider(base_url="http://insecure.example.test", token="x", fetch=lambda u, h: b"")


def test_missing_config_fails_loudly(monkeypatch):
    monkeypatch.delenv("CAPIQ_BASE_URL", raising=False)
    monkeypatch.delenv("CAPIQ_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        CapIQProvider()


def test_from_env_only_lists_configured_licensed_vendors(monkeypatch):
    for k in ("CAPIQ_BASE_URL", "CAPIQ_TOKEN", "PITCHBOOK_BASE_URL", "PITCHBOOK_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert {p.name for p in from_env(lambda u, h: b"")} == {"yahoo"}
    monkeypatch.setenv("CAPIQ_BASE_URL", BASE)
    monkeypatch.setenv("CAPIQ_TOKEN", "t")
    assert "capiq" in {p.name for p in from_env(lambda u, h: b"")}
