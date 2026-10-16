import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}
ROWS = [("max net leverage", 3.5), ("leverage Q1", 3.1), ("leverage Q2", 3.9), ("min cover", 2), ("cover Q1", 2.5)]


def setup(h, deal=None):
    wb = Workbook()
    for i, (k, v) in enumerate(ROWS, 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"] = k, v
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("cov.xlsx", b.getvalue(), "x")}, data={"deal": deal} if deal else {},
                 headers=h).json()["id"]

    def fact(metric, period, row, unit="x"):
        r = c.post("/facts", headers=h, json={"entity": "Co", "metric": metric, "period": period,
                                              "value": str(ROWS[row][1]), "unit": unit, "document_id": doc, "page": 1,
                                              "quote": f"Sheet!B{row + 1}: {ROWS[row][1]}"})
        assert r.status_code == 201, r.text
        return r.json()["id"]
    co = c.post("/portfolio/companies", json={"name": "Co"}, headers=h).json()["id"]
    return co, fact


def test_breach_headroom_and_alerts_with_cited_threshold():
    h = new_tenant(c, "cv1")
    co, fact = setup(h)
    thr = fact("debt.max_net_leverage_x", "cov", 0)
    for per, row in (("Q1", 1), ("Q2", 2)):
        o = fact("net_leverage_x", per, row)
        assert c.post(f"/portfolio/companies/{co}/observations", params={"fact_id": o}, headers=h).status_code == 201
    r = c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "net_leverage_x", "operator": "<=",
                                                             "threshold_fact_id": thr}, headers=h)
    assert r.status_code == 201
    s = c.get(f"/portfolio/companies/{co}/covenants", headers=h).json()
    tests = {t["period"]: t for t in s["covenants"][0]["tests"]}
    assert tests["Q1"]["status"] == "ok" and tests["Q1"]["headroom_pct"] == "11.4"
    assert tests["Q2"]["status"] == "breach" and tests["Q2"]["headroom_pct"] == "-11.4"
    assert [b["period"] for b in s["breaches"]] == ["Q2"] and s["breaches"][0]["threshold_fact_id"] == thr


def test_ge_operator_unit_mismatch_and_bad_inputs():
    h = new_tenant(c, "cv2")
    co, fact = setup(h)
    thr = fact("debt.min_interest_cover_x", "cov", 3)
    ok = fact("interest_cover_x", "Q1", 4)
    pct = fact("interest_cover_x", "Q2", 4, unit="pct")
    for f in (ok, pct):
        c.post(f"/portfolio/companies/{co}/observations", params={"fact_id": f}, headers=h)
    c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "interest_cover_x", "operator": ">=",
                                                         "threshold_fact_id": thr}, headers=h)
    tests = {t["period"]: t for t in c.get(f"/portfolio/companies/{co}/covenants", headers=h).json()["covenants"][0]["tests"]}
    assert tests["Q1"]["status"] == "ok" and tests["Q1"]["headroom_pct"] == "25.0"
    assert tests["Q2"]["status"] == "unit_mismatch"
    bad = {"kpi_metric": "x", "operator": "<=", "threshold_fact_id": 999999}
    assert c.post(f"/portfolio/companies/{co}/covenants", json=bad, headers=h).status_code == 422
    assert c.post(f"/portfolio/companies/{co}/covenants", json={**bad, "operator": "=", "threshold_fact_id": thr},
                  headers=h).status_code == 422
    fid = c.get("/facts", headers=h).json()[0]["id"]
    c.post(f"/facts/{fid}/review", headers=h, json={"action": "reject"})  # rejected fact can't be a threshold
    assert c.post(f"/portfolio/companies/{co}/covenants", json={**bad, "threshold_fact_id": fid}, headers=h).status_code == 422


def test_walled_key_sees_no_covenant_tests_from_hidden_documents():
    t = c.post("/admin/tenants", json={"name": "cv3"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}
    k = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"deals": ["alpha"]}, headers=ADMIN).json()
    walled = {"Authorization": f"Bearer {k['api_key']}"}
    co, fact = setup(owner, "bravo")
    thr, o = fact("debt.max_net_leverage_x", "cov", 0), fact("net_leverage_x", "Q2", 2)
    c.post(f"/portfolio/companies/{co}/observations", params={"fact_id": o}, headers=owner)
    c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "net_leverage_x", "operator": "<=",
                                                         "threshold_fact_id": thr}, headers=owner)
    assert c.get(f"/portfolio/companies/{co}/covenants", headers=owner).json()["breaches"]
    s = c.get(f"/portfolio/companies/{co}/covenants", headers=walled).json()
    assert s["breaches"] == [] and all(cv["tests"] == [] for cv in s["covenants"])
    viewer = {"Authorization": "Bearer " + c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "viewer"},
                                                    headers=ADMIN).json()["api_key"]}
    assert c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "x", "operator": "<=",
                                                                "threshold_fact_id": thr}, headers=viewer).status_code == 403
