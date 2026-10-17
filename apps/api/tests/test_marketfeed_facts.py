"""Market-data enterprise value → cited fact → trading comps. Feed responses are SYNTHETIC in the shape documented in
app/marketfeed_facts.py. The fact cites its feed record's row, so the value is checkable against the saved feed."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app import comps as comps_mod
from app.comps import EV_METRIC
from app.main import app
from app.rls import bind_tenant
from tests.helpers import new_tenant, new_tenant_id

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
        h, tid = new_tenant_id(c, "tev-cited")
        body = {"entity": "ACME", "period": "LTM", "source": "capiq", "url": URL, "token": "tok"}
        r = c.post("/market/tev-sync", json=body, headers=h)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["metric"] == EV_METRIC and out["value"] == "1300" and out["unit"] == "USD"
        assert out["quote"].startswith("row 2: ") and "tev=1300" in out["quote"]
        assert seen[0][1]["Authorization"] == "Bearer tok"
        with m.SessionLocal() as db:
            bind_tenant(db, tid)
            assert comps_mod._find(db, tid, "ACME", EV_METRIC, "LTM", None).as_of == "2026-10-16"  # the feed row's date
        again = c.post("/market/tev-sync", json=body, headers=h).json()
        assert again["fact_id"] == out["fact_id"]
        with m.SessionLocal() as db:
            bind_tenant(db, tid)
            assert comps_mod._find(db, tid, "ACME", EV_METRIC, "LTM", None).id == out["fact_id"]
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
        h, tid = new_tenant_id(c, "tev-scope")
        body = {"entity": "SCOPED", "period": "LTM", "source": "capiq", "url": URL, "token": "tok"}
        out = c.post("/market/tev-sync", json=body, headers=h).json()
        doc_id = out["document_id"]
        with m.SessionLocal() as db:
            bind_tenant(db, tid)
            assert _peer_ev(db, tid, "SCOPED", None).id == out["fact_id"]
            assert _peer_ev(db, tid, "SCOPED", None).label == "feed-capiq-SCOPED.csv"
            assert _peer_ev(db, tid, "SCOPED", {doc_id}).id == out["fact_id"]
            assert _peer_ev(db, tid, "SCOPED", set()) is None
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


def test_refresh_isolates_a_failed_feed_from_the_rest():
    def fetch(url, headers):
        if "bad" in url:
            raise OSError("feed down")
        return json.dumps({"data": [{"id": "ACME", "tev": 900, "currency": "USD", "date": "2026-10-16"}]}).encode()
    app.dependency_overrides[m.get_market_fetch] = lambda: fetch
    try:
        h, _ = new_tenant_id(c, "tev-refresh")
        item = {"entity": "ACME", "period": "LTM", "source": "capiq", "url": URL, "token": "tok"}
        bad = {**item, "entity": "BADCO", "url": "https://bad.example/feed"}
        r = c.post("/market/tev-refresh", json={"items": [bad, item]}, headers=h)
        assert r.status_code == 200, r.text
        bad_row, good_row = r.json()["results"]
        assert bad_row["ok"] is False and "feed" in bad_row["error"]
        assert good_row["ok"] is True and good_row["as_of"] == "2026-10-16"
    finally:
        app.dependency_overrides.clear()
