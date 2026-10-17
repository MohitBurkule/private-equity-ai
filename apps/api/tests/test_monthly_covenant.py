"""Monthly ledger figures → company observations → covenant watcher. A minimum net income covenant (cited to a
term sheet line) is breached only in the month where the ledger shows a loss. SYNTHETIC ledger and term text."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://ledger.example.com/synthetic"
TB = {
    "2026-08": {"period": "2026-08", "accounts": [{"name": "Sales", "type": "income", "amount_usd": 1000}]},
    "2026-09": {"period": "2026-09", "accounts": [{"name": "Staff", "type": "expense", "amount_usd": 300}]},
}
ROUTES = {f"{BASE}/v1/companies/ACME/trial-balance?period={p}": json.dumps(v).encode() for p, v in TB.items()}
TERM = "Minimum monthly net income covenant: USD 800 per month."


def test_monthly_loss_breaches_a_minimum_net_income_covenant(monkeypatch):
    h = new_tenant(c, "monthly-cov")
    up = c.post("/documents", files={"file": ("terms.csv", ("Term,Value\n" + TERM + ",800\n").encode(), "text/csv")}, headers=h)
    assert up.status_code == 200, up.text
    doc = up.json()
    fact = c.post("/facts", headers=h, json={"entity": "ACME", "metric": "covenant net_income_usd minimum",
                                             "period": "FY26", "value": "800", "unit": "USD",
                                             "document_id": doc["id"], "page": 1, "quote": TERM}).json()
    co = c.post("/portfolio/companies", json={"name": "ACME"}, headers=h).json()["id"]
    assert c.post(f"/portfolio/companies/{co}/covenants", headers=h, json={
        "kpi_metric": "net_income_usd", "operator": ">=", "threshold_fact_id": fact["id"]}).status_code == 201

    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(ROUTES))
    body = {"token": "tok", "deal": "ACME", "options": {"base_url": BASE, "company": "ACME",
                                                        "periods": "2026-08,2026-09",
                                                        "portfolio_company_id": str(co)}}
    assert c.post("/connectors/accounting/sync", json=body, headers=h).status_code == 200

    alerts = c.post("/alerts/scan", headers=h).json()["created"]
    breaches = [a for a in alerts if a["kind"] == "covenant"]
    assert len(breaches) == 1, alerts
    assert "2026-09" in breaches[0]["detail"] and "-300" in breaches[0]["detail"]


def test_unmapped_ledger_is_refused_and_stores_nothing(monkeypatch):
    h = new_tenant(c, "monthly-unmapped")
    c.post("/portfolio/companies", json={"name": "ACME"}, headers=h)
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(ROUTES))
    body = {"token": "tok", "options": {"base_url": BASE, "company": "ACME", "periods": "2026-08"}}
    r = c.post("/connectors/accounting/sync", json=body, headers=h)
    assert r.status_code == 502 and "portfolio_company_id" in r.text
    assert c.get("/documents", headers=h).json() == []
