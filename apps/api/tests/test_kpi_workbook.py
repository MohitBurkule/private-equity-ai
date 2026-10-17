"""Monthly KPI workbook ingest. SYNTHETIC: the company, figures and periods below are made up."""
import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _pack(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sep"
    ws.append(["SYNTHETIC monthly pack"])
    ws.append([])
    ws.append(["Metric", "Period", "Value", "Unit"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [("Revenue", "2026-09", 1234.5, "GBP m"), ("Adjusted EBITDA", "2026-09", 210, "GBP m"),
        ("Headcount", "2026-09", 412, "FTE"), ("Churn", "2026-09", 3, "%"), ("Revenue", "Sept", 1, "GBP m")]


def _upload(h, company_id, data, name="pack.xlsx"):
    return c.post(f"/portfolio/companies/{company_id}/kpi-pack", files={"file": (name, data, "application/vnd.ms-excel")},
                  headers=h)


def test_pack_rows_become_cited_observations_and_unmapped_rows_are_skipped():
    h = new_tenant(c, "kpi-pack")
    cid = c.post("/portfolio/companies", json={"name": "Acme"}, headers=h).json()["id"]
    r = _upload(h, cid, _pack(ROWS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["observations"]) == 3 and body["unchanged"] is False
    assert [s["cell"] for s in body["skipped"]] == ["Sep!C7", "Sep!C8"]
    kpis = c.get(f"/portfolio/companies/{cid}/kpis", headers=h).json()
    assert len(kpis) == 3


def test_same_pack_uploaded_twice_adds_nothing():
    h = new_tenant(c, "kpi-pack-again")
    cid = c.post("/portfolio/companies", json={"name": "Beta"}, headers=h).json()["id"]
    data = _pack(ROWS[:3])
    _upload(h, cid, data)
    again = _upload(h, cid, data).json()
    assert again["unchanged"] is True and again["observations"] == []


def test_unknown_company_is_refused():
    h = new_tenant(c, "kpi-pack-404")
    r = _upload(h, 999999, _pack(ROWS[:1]))
    assert r.status_code == 422 and "company not found" in r.json()["detail"]
