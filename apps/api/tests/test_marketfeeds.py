# Fixtures below are SYNTHETIC, shaped from vendor docs; see app/marketfeeds.py.
import json
from decimal import Decimal as D

import pytest

from app.marketdata import NoData
from app.marketfeeds import FactSetProvider, StooqProvider, YahooProvider


def fx(body):
    seen = {}

    def f(url, headers):
        seen["url"], seen["h"] = url, headers
        return body if isinstance(body, bytes) else json.dumps(body).encode()
    f.seen = seen
    return f


def test_stooq_quote_and_nodata():
    f = fx(b"Symbol,Date,Close\nAAPL.US,2026-10-15,201.50\n")
    q = StooqProvider("usd", f).quote("aapl.us")
    assert (q.price, q.currency, q.as_of, q.source) == (D("201.50"), "USD", "2026-10-15", "stooq")
    with pytest.raises(NoData):
        StooqProvider("usd", fx(b"Symbol,Date,Close\nXXX.US,N/D,N/D\n")).quote("xxx.us")
    with pytest.raises(NoData):
        StooqProvider("usd", fx(b"")).quote("x")


def test_yahoo_quote_incomplete_is_nodata():
    ok = {"chart": {"result": [{"meta": {"regularMarketPrice": 12.5, "currency": "gbp", "regularMarketTime": 1760486400}}]}}
    q = YahooProvider(fx(ok)).quote("VOD.L")
    assert q.price == D("12.5") and q.currency == "GBP" and q.as_of == "2025-10-15"
    for bad in ({"chart": {"result": None}}, {"chart": {"result": [{"meta": {"regularMarketPrice": 1}}]}}):
        with pytest.raises(NoData):
            YahooProvider(fx(bad)).quote("X")


def test_factset_latest_row_and_auth_header():
    body = {"data": [{"date": "2026-10-14", "price": 100, "currency": "USD"},
                     {"date": "2026-10-15", "price": 101.25, "currency": "USD"}]}
    f = fx(body)
    q = FactSetProvider("u-1", "k", f).quote("AAPL-US")
    assert q.price == D("101.25") and q.as_of == "2026-10-15" and q.source == "factset"
    assert f.seen["h"]["Authorization"].startswith("Basic ") and "ids=AAPL-US" in f.seen["url"]
    with pytest.raises(NoData):
        FactSetProvider("u", "k", fx({"data": [{"date": "2026-10-15", "price": None, "currency": "USD"}]})).quote("X")


def test_factset_needs_credentials(monkeypatch):
    monkeypatch.delenv("FACTSET_API_KEY", raising=False)
    monkeypatch.delenv("FACTSET_USERNAME_SERIAL", raising=False)
    with pytest.raises(RuntimeError):
        FactSetProvider()


def test_negative_or_nan_price_refused():
    with pytest.raises(NoData):
        YahooProvider(fx({"chart": {"result": [{"meta": {"regularMarketPrice": -1, "currency": "USD", "regularMarketTime": 1}}]}})).quote("X")


def test_quote_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app, get_market_fetch
    from tests.helpers import new_tenant

    c = TestClient(app)
    h = new_tenant(c, "mf1")
    app.dependency_overrides[get_market_fetch] = lambda: fx(b"Symbol,Date,Close\nA.US,2026-10-15,5.5\n")
    try:
        r = c.get("/market/quote", params={"symbol": "a.us", "provider": "stooq", "currency": "usd"}, headers=h)
        assert r.status_code == 200 and r.json()["price"] == "5.5" and r.json()["source"] == "stooq"
        assert c.get("/market/quote", params={"symbol": "a.us", "provider": "stooq"}, headers=h).status_code == 422
        assert c.get("/market/quote", params={"symbol": "a", "provider": "nope"}, headers=h).status_code == 422
        monkeypatch.delenv("FACTSET_API_KEY", raising=False)
        monkeypatch.delenv("FACTSET_USERNAME_SERIAL", raising=False)
        assert c.get("/market/quote", params={"symbol": "a", "provider": "factset"}, headers=h).status_code == 503
        assert c.get("/market/quote", params={"symbol": "a.us", "provider": "stooq", "currency": "usd"}).status_code == 401
        app.dependency_overrides[get_market_fetch] = lambda: fx(b"Symbol,Date,Close\nA.US,N/D,N/D\n")
        assert c.get("/market/quote", params={"symbol": "a.us", "provider": "stooq", "currency": "usd"}, headers=h).status_code == 404
    finally:
        app.dependency_overrides.pop(get_market_fetch, None)
