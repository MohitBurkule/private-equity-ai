"""Market-data enterprise value → cited fact → trading comps. Feed responses are SYNTHETIC in the shape documented in
app/marketfeed_facts.py. The fact cites its feed record's row, so the value is checkable against the saved feed."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app import comps as comps_mod
from app.comps import EV_METRIC
from app.main import app
from app.models import Fact
from tests.helpers import new_tenant

c = TestClient(app)
URL = "https://capiq.synthetic.test/v2/tev"
FEED = {"data": [
    {"id": "ACME", "tev": 1250.5, "currency": "USD", "date": "2026-10-15"},
    {"id": "ACME", "tev": 1300, "currency": "USD", "date": "2026-10-16"},
]}


def _feed(seen: list):
    def fetch(url, headers):
        seen.append((url, headers))
        return json.dumps(FEED).encode()
    return fetch


def test_latest_tev_becomes_cited_enterprise_value():
    seen = []
    app.dependency_overrides[m.get_market_fetch] = lambda: _feed(seen)
    try:
        h = new_tenant(c, "tev-cited")
        body = {"entity": "ACME", "period": "LTM", "source": "capiq", "url": URL, "token": "tok"}
        r = c.post("/market/tev-sync", json=body, headers=h)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["metric"] == EV_METRIC and out["value"] == "1300" and out["unit"] == "USD"
        assert out["quote"].startswith("row 2: ") and "tev=1300" in out["quote"]
        assert seen[0][1]["Authorization"] == "Bearer tok"
        again = c.post("/market/tev-sync", json=body, headers=h).json()
        assert again["fact_id"] == out["fact_id"]
        with m.SessionLocal() as db:
            fact = db.get(Fact, out["fact_id"])
            assert comps_mod._find(db, fact.tenant_id, "ACME", EV_METRIC, "LTM", None).id == out["fact_id"]
    finally:
        app.dependency_overrides.clear()


def test_non_https_or_empty_feed_is_refused(monkeypatch):
    app.dependency_overrides[m.get_market_fetch] = lambda: _feed([])
    try:
        h = new_tenant(c, "tev-bad")
        plain = {"entity": "ACME", "period": "LTM", "source": "capiq", "url": "http://x.test/v2", "token": "tok"}
        assert c.post("/market/tev-sync", json=plain, headers=h).status_code == 422
        app.dependency_overrides[m.get_market_fetch] = lambda: (lambda url, headers: b'{"data": []}')
        empty = dict(plain, url=URL)
        assert c.post("/market/tev-sync", json=empty, headers=h).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_peer_ev_respects_document_scope():
    from app.main import _peer_ev
    app.dependency_overrides[m.get_market_fetch] = lambda: _feed([])
    try:
        h = new_tenant(c, "tev-scope")
        body = {"entity": "SCOPED", "period": "LTM", "source": "capiq", "url": URL, "token": "tok"}
        out = c.post("/market/tev-sync", json=body, headers=h).json()
        doc_id = out["document_id"]
        with m.SessionLocal() as db:
            tenant = db.get(Fact, out["fact_id"]).tenant_id
            assert _peer_ev(db, tenant, "SCOPED", None).id == out["fact_id"]
            assert _peer_ev(db, tenant, "SCOPED", None).label == "feed-capiq-SCOPED.csv"
            assert _peer_ev(db, tenant, "SCOPED", {doc_id}).id == out["fact_id"]
            assert _peer_ev(db, tenant, "SCOPED", set()) is None
    finally:
        app.dependency_overrides.clear()


def test_unreadable_feed_is_422_not_500():
    app.dependency_overrides[m.get_market_fetch] = lambda: _feed([])
    try:
        h = new_tenant(c, "tev-badurl")
        body = {"entity": "Saia, Inc.", "period": "LTM", "source": "capiq",
                "url": "https://capiq.synthetic.test/v2/tev?symbol=Saia, Inc.", "token": "tok"}
        app.dependency_overrides[m.get_market_fetch] = lambda: _bad_url_fetch
        r = c.post("/market/tev-sync", json=body, headers=h)
        assert r.status_code == 422 and "could not be read" in r.text
    finally:
        app.dependency_overrides.clear()


def _bad_url_fetch(url, headers):
    raise ValueError("URL can't contain control characters")
