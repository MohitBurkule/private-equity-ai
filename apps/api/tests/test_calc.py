import io
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}

ROWS = [("revenue FY23", 1000), ("revenue 9M24", 800), ("revenue 9M23", 700), ("total debt", 500),
        ("lease liabilities", 50), ("cash", 120), ("current assets", 400), ("current liabilities", 300),
        ("short-term debt", 60)]


def setup(h, deal=None):
    wb = Workbook()
    for i, (k, v) in enumerate(ROWS, 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"] = k, v
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, data={"deal": deal} if deal else {},
                 headers=h).json()["id"]

    def fact(metric, period, row):
        r = c.post("/facts", headers=h, json={"entity": "A", "metric": metric, "period": period,
                                              "value": str(ROWS[row][1]), "unit": "USD", "document_id": doc,
                                              "page": 1, "quote": f"Sheet!B{row + 1}: {ROWS[row][1]:,}"})
        assert r.status_code == 201, r.text
    return doc, fact


def test_ltm_net_debt_nwc_with_traceable_inputs():
    h = new_tenant(c, "calc1")
    _, fact = setup(h)
    fact("revenue", "FY23", 0)
    fact("revenue", "9M24", 1)
    fact("revenue", "9M23", 2)
    for m, row in (("total_debt", 3), ("lease_liabilities", 4), ("cash", 5), ("current_assets", 6),
                   ("current_liabilities", 7), ("short_term_debt", 8)):
        fact(m, "FY23", row)
    r = c.get("/calc/ltm", params={"entity": "A", "metric": "revenue", "fy": "FY23", "ytd": "9M24",
                                   "ytd_prior": "9M23"}, headers=h).json()
    assert r["ok"] and Decimal(r["value"]) == 1100 and len(r["inputs"]) == 3
    assert all(i["sources"][0]["quote"].startswith("Sheet!B") for i in r["inputs"])
    nd = c.get("/calc/net-debt", params={"entity": "A", "period": "FY23"}, headers=h).json()
    assert Decimal(nd["value"]) == 430
    nd2 = c.get("/calc/net-debt", params={"entity": "A", "period": "FY23", "include_leases": "false"}, headers=h).json()
    assert Decimal(nd2["value"]) == 380
    w = c.get("/calc/nwc", params={"entity": "A", "period": "FY23"}, headers=h).json()
    assert Decimal(w["value"]) == (400 - 120) - (300 - 60)


def test_missing_inputs_are_listed_not_defaulted_and_rejected_facts_ignored():
    h = new_tenant(c, "calc2")
    _, fact = setup(h)
    fact("total_debt", "FY23", 3)
    fact("cash", "FY23", 5)
    nd = c.get("/calc/net-debt", params={"entity": "A", "period": "FY23"}, headers=h).json()
    assert nd["ok"] is False and nd["value"] is None and nd["missing"] == ["leases: lease_liabilities for FY23"]
    fid = c.get("/facts", headers=h).json()[1]["id"]
    c.post(f"/facts/{fid}/review", headers=h, json={"action": "reject"})
    nd = c.get("/calc/net-debt", params={"entity": "A", "period": "FY23", "include_leases": "false"}, headers=h).json()
    assert nd["ok"] is False and "cash" in nd["missing"][0]


def test_unit_mismatch_is_a_problem_not_a_number():
    h = new_tenant(c, "calc3")
    doc, _ = setup(h)
    for metric, row, unit in (("total_debt", 3, "USD"), ("cash", 5, "EUR")):
        c.post("/facts", headers=h, json={"entity": "A", "metric": metric, "period": "FY23", "value": str(ROWS[row][1]),
                                          "unit": unit, "document_id": doc, "page": 1,
                                          "quote": f"Sheet!B{row + 1}: {ROWS[row][1]:,}"})
    r = c.get("/calc/net-debt", params={"entity": "A", "period": "FY23", "include_leases": "false"}, headers=h).json()
    assert r["ok"] is False and r["problems"]


def test_walled_key_cannot_compute_from_hidden_facts():
    t = c.post("/admin/tenants", json={"name": "calc4"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}
    k = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"deals": ["alpha"]}, headers=ADMIN).json()
    walled = {"Authorization": f"Bearer {k['api_key']}"}
    _, fact = setup(owner, "bravo")
    fact("total_debt", "FY23", 3)
    fact("cash", "FY23", 5)
    p = {"entity": "A", "period": "FY23", "include_leases": "false"}
    assert c.get("/calc/net-debt", params=p, headers=owner).json()["ok"] is True
    r = c.get("/calc/net-debt", params=p, headers=walled).json()
    assert r["ok"] is False and len(r["missing"]) == 2
