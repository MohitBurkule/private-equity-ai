"""Fund administrator API → sync → cited fund facts. SYNTHETIC responses in the shape the connector documents
(app/connectors/fundadmin.py). The sync stores a workbook; the fund-admin reader then cites each figure to its cell."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://fundadmin.example.com/synthetic/fundadmin"
ROUTES = {
    f"{BASE}/v1/funds/FUND-7/capital-calls": {"items": [
        {"call_no": 4, "date": "2026-09-30", "amount_usd": 12500000}]},
    f"{BASE}/v1/funds/FUND-7/nav": {"as_of": "2026-06-30", "nav_usd": 214000000},
}


def test_api_sync_then_cited_facts_and_kpis(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({k: json.dumps(v).encode() for k, v in ROUTES.items()}))
    h = new_tenant(c, "fundadmin-api")
    body = {"token": "tok", "deal": "fund-vii", "options": {"base_url": BASE, "fund": "FUND-7"}}
    synced = c.post("/connectors/fundadmin/sync", json=body, headers=h)
    assert synced.status_code == 200, synced.text
    (item,) = synced.json()["ingested"]
    assert item["filename"] == "FUND-7-fund-admin.xlsx"

    facts = c.post(f"/documents/{item['document_id']}/fund-admin/facts", params={"entity": "Fund VII"}, headers=h)
    assert facts.status_code == 201 and len(facts.json()["created"]) == 2 and facts.json()["skipped"] == []
    co = c.post("/portfolio/companies", json={"name": "Fund VII"}, headers=h).json()["id"]
    for fid in facts.json()["created"]:
        assert c.post(f"/portfolio/companies/{co}/observations?fact_id={fid}", headers=h).status_code == 201
    kpis = {k["metric"]: float(k["value"]) for k in c.get(f"/portfolio/companies/{co}/kpis", headers=h).json()}
    assert kpis == {"capital_call_usd": 12_500_000.0, "nav_usd": 214_000_000.0}


def test_sync_stores_cited_facts_without_a_second_call(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({k: json.dumps(v).encode() for k, v in ROUTES.items()}))
    h = new_tenant(c, "fundadmin-auto")
    body = {"token": "tok", "deal": "fund-vii", "options": {"base_url": BASE, "fund": "FUND-7"}}
    assert c.post("/connectors/fundadmin/sync", json=body, headers=h).status_code == 200
    facts = c.get("/facts", params={"entity": "fund-vii"}, headers=h).json()
    assert sorted(f["metric"] for f in facts) == ["capital_call_usd", "nav_usd"]


def test_unexpected_shape_is_a_connector_error(monkeypatch):
    bad = {f"{BASE}/v1/funds/FUND-7/capital-calls": {"rows": []}, f"{BASE}/v1/funds/FUND-7/nav": {}}
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({k: json.dumps(v).encode() for k, v in bad.items()}))
    h = new_tenant(c, "fundadmin-bad")
    body = {"token": "tok", "options": {"base_url": BASE, "fund": "FUND-7"}}
    r = c.post("/connectors/fundadmin/sync", json=body, headers=h)
    assert r.status_code == 502 and "expected shape" in r.text


def test_same_flow_through_wiremock_stubs(monkeypatch):
    """Runs the sync over real HTTP against WireMock, loaded with the SYNTHETIC fund-admin stubs from
    deploy/mocks/wiremock/mappings/fund-admin.json. Skipped without WIREMOCK_JAR or WIREMOCK_URL."""
    import json as _json
    from pathlib import Path

    import pytest

    from tests.mock_servers import WireMock, rewrite_http

    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR or WIREMOCK_URL not set")
    stubs = Path(__file__).resolve().parents[3] / "deploy" / "mocks" / "wiremock" / "mappings" / "fund-admin.json"
    with WireMock() as wm:
        for mapping in _json.loads(stubs.read_text())["mappings"]:
            import urllib.request
            urllib.request.urlopen(urllib.request.Request(f"{wm.base}/__admin/mappings",
                                                          data=_json.dumps(mapping).encode(), method="POST",
                                                          headers={"content-type": "application/json"}), timeout=5).read()
        monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({BASE: wm.base + "/synthetic/fundadmin"}))
        h = new_tenant(c, "fundadmin-wm")
        body = {"token": "tok", "deal": "fund-vii", "options": {"base_url": BASE, "fund": "FUND-7"}}
        synced = c.post("/connectors/fundadmin/sync", json=body, headers=h)
        assert synced.status_code == 200, synced.text
        assert len(synced.json()["ingested"]) == 1
