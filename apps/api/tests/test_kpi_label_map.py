"""Per-company label map for KPI packs. SYNTHETIC: the company, labels and figures below are made up."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_kpi_workbook import _pack, _upload

c = TestClient(app)
ROWS = [("Sales", "2026-09", 77, "GBP m"), ("Revenue", "2026-09", 80, "GBP m"), ("Turnover", "2026-09", 9, "GBP m")]


def test_company_label_is_mapped_and_default_still_works_unknown_still_skipped():
    h = new_tenant(c, "label-map")
    cid = c.post("/portfolio/companies", json={"name": "Synth Co"}, headers=h).json()["id"]
    assert c.put(f"/portfolio/companies/{cid}/label-map", json={"labels": {"Sales": "revenue"}}, headers=h).status_code == 200
    body = _upload(h, cid, _pack(ROWS)).json()
    assert len(body["observations"]) == 2
    assert [s["cell"] for s in body["skipped"]] == ["Sep!C6"]
    kpis = c.get(f"/portfolio/companies/{cid}/kpis", headers=h).json()
    assert {k["metric"] for k in kpis} == {"revenue"}


def test_label_map_rejects_unknown_kpi_and_other_tenant():
    h = new_tenant(c, "label-map-bad")
    cid = c.post("/portfolio/companies", json={"name": "Synth Two"}, headers=h).json()["id"]
    bad = c.put(f"/portfolio/companies/{cid}/label-map", json={"labels": {"Sales": "made_up"}}, headers=h)
    assert bad.status_code == 422
    other = new_tenant(c, "label-map-other")
    assert c.put(f"/portfolio/companies/{cid}/label-map", json={"labels": {"Sales": "revenue"}}, headers=other).status_code == 422
