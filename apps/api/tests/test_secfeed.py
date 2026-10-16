import json
from pathlib import Path

import pytest

from app.secfeed import default_fetch, lookup_cik, parse_submissions, recent_filings

FX = Path(__file__).parent / "fixtures"


def _load(n):
    return json.loads((FX / n).read_text())


def test_lookup_cik_pads_and_ignores_case():
    t = _load("sec_company_tickers.json")
    assert lookup_cik(t, "aapl") == ("0000320193", "Apple Inc.")
    assert lookup_cik(t, "NOPE") is None


def test_parse_submissions_urls_and_form_filter():
    fl = parse_submissions(_load("sec_submissions_apple.json"), forms=None)
    assert fl and all(f.url.startswith("https://www.sec.gov/Archives/edgar/data/320193/") for f in fl)
    assert all("xsl" not in f.url for f in fl)
    only = parse_submissions(_load("sec_submissions_apple.json"), forms={"8-K"})
    assert all(f.form == "8-K" for f in only)


def test_recent_filings_with_injected_fetch_and_unknown_ticker():
    docs = {"https://www.sec.gov/files/company_tickers.json": (FX / "sec_company_tickers.json").read_bytes(),
            "https://data.sec.gov/submissions/CIK0000320193.json": (FX / "sec_submissions_apple.json").read_bytes()}
    assert recent_filings("NOPE", docs.__getitem__) == []
    assert isinstance(recent_filings("AAPL", docs.__getitem__), list)


def test_default_fetch_requires_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError):
        default_fetch("https://data.sec.gov/x")


def test_endpoint_auth_and_override():
    from fastapi.testclient import TestClient

    from app.main import app, get_sec_fetch
    from tests.helpers import new_tenant
    c = TestClient(app)
    assert c.get("/sec/filings", params={"ticker": "AAPL"}).status_code == 401
    h = new_tenant(c, "sec-t")
    r = c.get("/sec/filings", params={"ticker": "AAPL"}, headers=h)
    assert r.status_code in (200, 503)
    docs = {"https://www.sec.gov/files/company_tickers.json": (FX / "sec_company_tickers.json").read_bytes(),
            "https://data.sec.gov/submissions/CIK0000320193.json": (FX / "sec_submissions_apple.json").read_bytes()}
    app.dependency_overrides[get_sec_fetch] = lambda: docs.__getitem__
    try:
        r = c.get("/sec/filings", params={"ticker": "AAPL"}, headers=h)
        assert r.status_code == 200 and isinstance(r.json(), list)
    finally:
        app.dependency_overrides.pop(get_sec_fetch)
