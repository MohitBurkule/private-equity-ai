"""Market-data EV sync against WireMock. The feed is SYNTHETIC, in the shape documented in app/marketfeed_facts.py.
Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import comps as comps_mod
from app.comps import EV_METRIC
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
URL = "https://capiq.synthetic.test/v2/tev"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def test_tev_sync_through_wiremock_feeds_comps(wm, monkeypatch):
    feed = {"data": [{"id": "SYN-XPO", "tev": 12000.25, "currency": "usd", "date": "2026-10-15"},
                     {"id": "SYN-XPO", "tev": 12400, "currency": "usd", "date": "2026-10-16"}]}
    wm.stub("GET", {"urlPath": "/v2/tev"}, body=json.dumps(feed), headers={"Content-Type": "application/json"})
    fetch = rewrite_http({"https://capiq.synthetic.test/": wm.base + "/"})
    app.dependency_overrides[m.get_market_fetch] = lambda: fetch
    try:
        h = new_tenant(c, "tev-wm")
        body = {"entity": "SYN-XPO", "period": "LTM", "source": "capiq", "url": URL, "token": "tok"}
        out = c.post("/market/tev-sync", json=body, headers=h).json()
        assert out["value"] == "12400" and out["unit"] == "USD" and "tev=12400" in out["quote"]
        with m.SessionLocal() as db:
            from app.models import Fact
            tenant = db.get(Fact, out["fact_id"]).tenant_id
            assert comps_mod._find(db, tenant, "SYN-XPO", EV_METRIC, "LTM", None).id == out["fact_id"]
    finally:
        app.dependency_overrides.clear()
