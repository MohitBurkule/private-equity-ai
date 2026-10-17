"""Macro rates and FX. The ECB fixture is a real saved response; the FRED fixture is SYNTHETIC (no key here)."""
from pathlib import Path

import pytest

from app import macrodata as md
from app.marketdata import NoData

FIX = Path(__file__).parent / "fixtures" / "macro"


def _ecb(url, headers):
    assert url.startswith("https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A")
    return (FIX / "ecb_exr_usd_eur.xml").read_bytes()


def test_ecb_fx_is_newest_day_with_its_date_and_source():
    q = md.EcbFxProvider(_ecb).quote("usd")
    assert (q.symbol, str(q.price), q.currency, q.as_of, q.source) == ("USD/EUR", "1.1253", "EUR", "2026-10-16", "ecb")


def test_ecb_empty_or_garbled_answer_is_no_data():
    with pytest.raises(NoData):
        md.EcbFxProvider(lambda u, h: b"<root/>").quote("USD")
    with pytest.raises(NoData):
        md.EcbFxProvider(lambda u, h: b"not xml").quote("USD")


def test_fred_skips_missing_days_and_keeps_the_date():
    body = b'{"observations":[{"date":"2026-10-16","value":"."},{"date":"2026-10-15","value":"4.21"}]}'
    q = md.FredProvider("k", fetch=lambda u, h: body).quote("dgs10")
    assert (q.symbol, str(q.price), q.currency, q.as_of, q.source) == ("DGS10", "4.21", "PCT", "2026-10-15", "fred")


def test_fred_all_missing_is_no_data():
    with pytest.raises(NoData):
        md.FredProvider("k", fetch=lambda u, h: b'{"observations":[{"date":"2026-10-16","value":"."}]}').quote("DGS10")


def test_fred_keyless_csv_skips_missing_and_keeps_date():
    # SYNTHETIC: shaped like the public FRED graph CSV (observation_date,<ID>; '.' for missing)
    body = b"observation_date,SOFR\n2026-10-14,3.60\n2026-10-15,.\n2026-10-16,3.62\n"
    seen = []
    q = md.FredProvider(fetch=lambda u, h: (seen.append(u), body)[1]).quote("sofr")
    assert (str(q.price), q.as_of, q.source) == ("3.62", "2026-10-16", "fred")
    assert "fredgraph.csv" in seen[0] and "api_key" not in seen[0]


def test_fred_keyless_csv_all_missing_is_no_data():
    with pytest.raises(NoData):
        md.FredProvider(fetch=lambda u, h: b"observation_date,SOFR\n2026-10-16,.\n").quote("SOFR")


def test_fred_is_always_registered_key_or_not(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert [p.name for p in md.registered(_ecb)] == ["ecb", "fred"]


def test_market_quote_endpoint_serves_ecb(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app, get_market_fetch
    from tests.helpers import new_tenant

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    app.dependency_overrides[get_market_fetch] = lambda: _ecb
    try:
        c = TestClient(app)
        h = new_tenant(c, "macro-ep")
        r = c.get("/market/quote", params={"symbol": "usd", "provider": "ecb"}, headers=h)
        assert r.status_code == 200 and r.json()["as_of"] == "2026-10-16" and r.json()["source"] == "ecb"
    finally:
        app.dependency_overrides.pop(get_market_fetch, None)
