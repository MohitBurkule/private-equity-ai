"""Portfolio-company accounting sync against WireMock (open-source jar). The ledger stubs are SYNTHETIC and follow
the shape in app/connectors/accounting.py. Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
BASE = "https://ledger.example.com/synthetic"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def test_ledger_sync_through_wiremock_is_cited(wm, monkeypatch):
    j = {"Content-Type": "application/json"}
    for period, rev, exp in (("2026-08", 1500, 500), ("2026-09", 1200, 1500)):
        wm.stub("GET", {"urlPath": "/synthetic/v1/companies/ACME/trial-balance",
                        "queryParameters": {"period": {"equalTo": period}}}, headers=j, body=json.dumps(
            {"period": period, "accounts": [{"name": "Sales", "type": "income", "amount_usd": rev},
                                            {"name": "Staff", "type": "expense", "amount_usd": exp}]}))
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({BASE + "/": wm.base + "/synthetic/"}))
    h = new_tenant(c, "accounting-wm")
    co = c.post("/portfolio/companies", json={"name": "ACME"}, headers=h).json()["id"]
    body = {"token": "tok", "deal": "acme", "options": {"base_url": BASE, "company": "ACME", "periods": "2026-08,2026-09", "portfolio_company_id": str(co)}}
    out = c.post("/connectors/accounting/sync", json=body, headers=h).json()
    (d,) = out["ingested"]
    assert c.get(f"/documents/{d['document_id']}/source", headers=h).json()["connector"] == "accounting"
    assert c.post(f"/documents/{d['document_id']}/fund-admin/facts", params={"entity": "ACME"},
                  headers=h).status_code == 201
    got = {(f["metric"], f["period"]): float(f["value"]) for f in c.get("/facts", params={"entity": "ACME"}, headers=h).json()}
    assert got[("net_income_usd", "2026-09")] == -300.0 and got[("revenue_usd", "2026-08")] == 1500.0
