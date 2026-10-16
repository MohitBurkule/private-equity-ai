from decimal import Decimal

from app.xbrl import candidates, crosscheck, load_companyfacts, period_from_context

DOC = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"start": "2018-01-01", "end": "2018-12-31", "val": 100, "accn": "A1", "form": "10-K", "filed": "2019-02-01"},
    {"start": "2018-01-01", "end": "2018-12-31", "val": 100, "accn": "A2", "form": "10-K", "filed": "2020-02-01"},
    {"start": "2017-01-01", "end": "2017-12-31", "val": 90, "accn": "A1", "form": "10-K", "filed": "2019-02-01"},
    {"start": "2017-01-01", "end": "2017-12-31", "val": 95, "accn": "A2", "form": "10-K", "filed": "2020-02-01"},
]}}}}}


def test_contexts():
    assert period_from_context("P01_01_2025To12_31_2025") == ("2025-01-01", "2025-12-31")
    assert period_from_context("PAsOn12_31_2025") == (None, "2025-12-31")
    assert period_from_context("garbage") is None


def test_match_duplicates_are_not_conflicts():
    f = load_companyfacts(DOC)
    r = crosscheck(Decimal(100), candidates(f, "us-gaap:Revenues", "2018-12-31", "2018-01-01"))
    assert r.status == "match" and len(r.matched) == 2


def test_restatement_is_reported_not_hidden():
    f = load_companyfacts(DOC)
    r = crosscheck(Decimal(90), candidates(f, "us-gaap:Revenues", "2017-12-31"))
    assert r.status == "restated" and r.distinct_values == [Decimal(90), Decimal(95)]
    only_new = crosscheck(Decimal(95), candidates(f, "us-gaap:Revenues", "2017-12-31", accn="A2"))
    assert only_new.status == "match"


def test_mismatch_and_not_found():
    f = load_companyfacts(DOC)
    assert crosscheck(Decimal(1), candidates(f, "us-gaap:Revenues", "2018-12-31")).status == "mismatch"
    assert crosscheck(Decimal(1), candidates(f, "us-gaap:Nope", "2018-12-31")).status == "not_found"


def test_edgar_url_and_injectable_getter():
    import json

    from app.edgar import fetch_companyfacts
    seen = []

    def fake(url):
        seen.append(url)
        return json.dumps(DOC).encode()

    assert fetch_companyfacts(66740, fake) == DOC
    assert seen == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"]


def test_xbrl_endpoint_with_cached_data(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as m
    from tests.helpers import new_tenant
    monkeypatch.setattr(m, "get_companyfacts", lambda cik: DOC)
    c = TestClient(m.app)
    h = new_tenant(c, "xbrl-t")
    r = c.get("/xbrl/check", params={"cik": 1, "concept": "us-gaap:Revenues", "end": "2017-12-31",
                                     "value": "90"}, headers=h)
    assert r.json()["status"] == "restated" and r.json()["distinct_values"] == ["90", "95"]
    assert c.get("/xbrl/check", params={"cik": 1, "concept": "us-gaap:Revenues", "end": "2017-12-31",
                                        "value": "90"}).status_code == 401

    def boom(cik):
        raise RuntimeError("SEC_USER_AGENT is not set")
    monkeypatch.setattr(m, "get_companyfacts", boom)
    assert c.get("/xbrl/check", params={"cik": 1, "concept": "x", "end": "2017-12-31", "value": "1"},
                 headers=h).status_code == 502
