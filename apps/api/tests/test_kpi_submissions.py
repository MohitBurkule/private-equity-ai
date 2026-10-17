"""Missing-submission tracker: a company counts as submitted for a period only when it has a current, citable KPI
for that period. Reuses the accounting sync fixture so the submitted KPIs are real cited observations."""

from tests.helpers import new_tenant
from tests.test_accounting_flow import _sync, c


def test_submitted_and_missing_split_by_period(monkeypatch):
    h = new_tenant(c, "kpi-submissions")
    assert _sync(h, monkeypatch).status_code == 200
    c.post("/portfolio/companies", json={"name": "SILENT"}, headers=h)

    r = c.get("/portfolio/submissions", params={"period": "2026-08"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["name"] for s in body["submitted"]] == ["ACME"]
    assert body["submitted"][0]["metrics"]
    assert [m["name"] for m in body["missing"]] == ["SILENT"]
    assert body["pct_submitted"] == 50.0


def test_period_with_no_filings_marks_everyone_missing(monkeypatch):
    h = new_tenant(c, "kpi-submissions-empty")
    c.post("/portfolio/companies", json={"name": "QUIET"}, headers=h)
    body = c.get("/portfolio/submissions", params={"period": "2030-01"}, headers=h).json()
    assert body["submitted"] == []
    assert [m["name"] for m in body["missing"]] == ["QUIET"]
    assert body["pct_submitted"] == 0.0


def test_no_companies_has_no_percentage():
    h = new_tenant(c, "kpi-submissions-none")
    body = c.get("/portfolio/submissions", params={"period": "2026-08"}, headers=h).json()
    assert body == {"period": "2026-08", "submitted": [], "missing": [], "pct_submitted": None}
