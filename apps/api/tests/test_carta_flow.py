"""Carta cap table → sync → cited share and ownership facts, one entity per holder. SYNTHETIC holdings in the
shape documented in app/connectors/carta.py."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://carta.example.com/synthetic"
AS_OF = "2026-09-30"
HOLDINGS = {"holdings": [
    {"holder": "Founder A", "share_class": "Common", "shares": 4000000, "ownership_pct": 40},
    {"holder": "Seed Fund", "share_class": "Series A Preferred", "shares": 2000000, "ownership_pct": 20},
    {"holder": "Option Pool", "share_class": "Common", "shares": 1000000, "ownership_pct": 10}]}
ROUTE = f"{BASE}/v1/companies/ACME/cap-table?as_of={AS_OF}"


def test_cap_table_holdings_become_cited_facts_per_holder(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({ROUTE: json.dumps(HOLDINGS).encode()}))
    h = new_tenant(c, "carta-flow")
    body = {"token": "tok", "deal": "acme", "options": {"base_url": BASE, "company": "ACME", "as_of": AS_OF}}
    synced = c.post("/connectors/carta/sync", json=body, headers=h)
    assert synced.status_code == 200, synced.text
    (item,) = synced.json()["ingested"]
    assert item["filename"] == "ACME-cap-table.xlsx"

    facts = c.post(f"/documents/{item['document_id']}/fund-admin/facts", params={"entity": "ACME"}, headers=h)
    assert facts.status_code == 201 and facts.json()["skipped"] == []
    got = {(f["entity"], f["metric"]): float(f["value"]) for f in c.get("/facts", headers=h).json()}
    assert got[("Seed Fund", "shares Series A Preferred")] == 2000000.0
    assert got[("Seed Fund", "ownership_pct Series A Preferred")] == 20.0
    assert got[("Founder A", "shares Common")] == 4000000.0
    again = c.post("/connectors/carta/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
