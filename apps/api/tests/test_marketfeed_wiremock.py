"""Market-data EV sync against WireMock. The feed is SYNTHETIC, in the shape documented in app/marketfeed_facts.py.
Skipped unless WIREMOCK_JAR is set."""
import json
import os
import ssl
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import comps as comps_mod
from app.comps import EV_METRIC
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
STUBS_DIR = Path(__file__).resolve().parents[3] / "deploy" / "mocks" / "wiremock" / "mappings"
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


TLS_KEYSTORE = os.environ.get("WIREMOCK_TLS_KEYSTORE", "")
TLS_CERT = Path(TLS_KEYSTORE).parent / "cert.pem" if TLS_KEYSTORE else None


@pytest.fixture(scope="module")
def wm_tls():
    if not WireMock().available or not TLS_KEYSTORE or not Path(TLS_KEYSTORE).is_file():
        pytest.skip("WIREMOCK_JAR and WIREMOCK_TLS_KEYSTORE (deploy/mocks/tls/make-cert.sh) not set")
    with WireMock() as w:
        yield w


def test_tev_sync_over_https_with_the_synthetic_mock_cert(wm_tls):
    """The feed is fetched over https, with the mock's self-signed CA as the only trusted root; no http rewrite."""
    stub = json.loads((STUBS_DIR / "marketfeed-tev.json").read_text())["mappings"][0]
    urllib.request.urlopen(urllib.request.Request(f"{wm_tls.base}/__admin/mappings", data=json.dumps(stub).encode(),
                                                  method="POST", headers={"content-type": "application/json"}),
                           timeout=5).read()
    ctx = ssl.create_default_context(cafile=str(TLS_CERT))

    def fetch(url, headers):
        req = urllib.request.Request(url.replace("https://localhost/", f"{wm_tls.https_base}/"), headers=headers)
        return urllib.request.urlopen(req, timeout=5, context=ctx).read()

    app.dependency_overrides[m.get_market_fetch] = lambda: fetch
    try:
        h = new_tenant(c, "tev-tls")
        url = "https://localhost/v2/tev?symbol=ACME"
        out = c.post("/market/tev-sync", json={"entity": "ACME", "period": "LTM", "source": "capiq", "url": url,
                                               "token": "tok"}, headers=h).json()
        assert out["value"] == "4480" and "tev=4480" in out["quote"]
    finally:
        app.dependency_overrides.clear()
