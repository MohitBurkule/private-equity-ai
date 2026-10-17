"""Portfolio-company trial balances → sync → cited monthly revenue and net income. SYNTHETIC ledger in the shape
documented in app/connectors/accounting.py. Each figure is cited to its cell in the stored workbook."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://ledger.example.com/synthetic"
TB = {
    "2026-08": {"period": "2026-08", "accounts": [
        {"name": "Subscriptions", "type": "income", "amount_usd": 1000},
        {"name": "Services", "type": "income", "amount_usd": 500},
        {"name": "Hosting", "type": "expense", "amount_usd": 300},
        {"name": "Payroll", "type": "expense", "amount_usd": 200},
        {"name": "Cash", "type": "other", "amount_usd": 9999}]},
    "2026-09": {"period": "2026-09", "accounts": [
        {"name": "Subscriptions", "type": "income", "amount_usd": 1200},
        {"name": "Payroll", "type": "expense", "amount_usd": 1500}]},
}
ROUTES = {f"{BASE}/v1/companies/ACME/trial-balance?period={p}": v for p, v in TB.items()}


def _sync(h, monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({k: json.dumps(v).encode() for k, v in ROUTES.items()}))
    body = {"token": "tok", "deal": "acme", "options": {"base_url": BASE, "company": "ACME", "periods": "2026-08,2026-09"}}
    return c.post("/connectors/accounting/sync", json=body, headers=h)


def test_trial_balances_become_cited_monthly_kpis(monkeypatch):
    h = new_tenant(c, "accounting-flow")
    synced = _sync(h, monkeypatch)
    assert synced.status_code == 200, synced.text
    (item,) = synced.json()["ingested"]
    assert item["filename"] == "ACME-monthly.xlsx"

    facts = c.post(f"/documents/{item['document_id']}/fund-admin/facts", params={"entity": "ACME"}, headers=h)
    assert facts.status_code == 201 and facts.json()["skipped"] == []
    got = {(f["metric"], f["period"]): float(f["value"]) for f in c.get("/facts", params={"entity": "ACME"}, headers=h).json()}
    assert got == {("revenue_usd", "2026-08"): 1500.0, ("net_income_usd", "2026-08"): 1000.0,
                   ("revenue_usd", "2026-09"): 1200.0, ("net_income_usd", "2026-09"): -300.0}


def test_resync_is_a_no_op_and_bad_periods_are_refused(monkeypatch):
    h = new_tenant(c, "accounting-again")
    _sync(h, monkeypatch)
    again = _sync(h, monkeypatch).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
    bad = c.post("/connectors/accounting/sync", headers=h, json={"token": "tok", "options": {
        "base_url": BASE, "company": "ACME", "periods": "August"}})
    assert bad.status_code == 502
