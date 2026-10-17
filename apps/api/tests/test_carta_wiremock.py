"""Carta cap table sync against WireMock (open-source jar). The holdings are SYNTHETIC and follow the shape in
app/connectors/carta.py. Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
BASE = "https://carta.example.com/synthetic"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def test_cap_table_sync_through_wiremock_is_cited(wm, monkeypatch):
    wm.stub("GET", {"urlPath": "/synthetic/v1/companies/ACME/cap-table",
                    "queryParameters": {"as_of": {"equalTo": "2026-09-30"}}},
            headers={"Content-Type": "application/json"}, body=json.dumps({"holdings": [
                {"holder": "Founder B", "share_class": "Common", "shares": 3000000, "ownership_pct": 30}]}))
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({BASE + "/": wm.base + "/synthetic/"}))
    h = new_tenant(c, "carta-wm")
    body = {"token": "tok", "deal": "acme", "options": {"base_url": BASE, "company": "ACME", "as_of": "2026-09-30"}}
    out = c.post("/connectors/carta/sync", json=body, headers=h).json()
    (d,) = out["ingested"]
    assert c.get(f"/documents/{d['document_id']}/source", headers=h).json()["connector"] == "carta"
    assert c.post(f"/documents/{d['document_id']}/fund-admin/facts", params={"entity": "ACME"},
                  headers=h).status_code == 201
    got = {(f["entity"], f["metric"]): float(f["value"]) for f in c.get("/facts", headers=h).json()}
    assert got[("Founder B", "shares Common")] == 3000000.0 and got[("Founder B", "ownership_pct Common")] == 30.0
