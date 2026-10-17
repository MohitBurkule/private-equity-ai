import io

from docx import Document as Docx
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def xlsx(rows):
    wb = Workbook()
    for i, (k, v) in enumerate(rows, 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"] = k, v
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def up(h, rows, name, deal=None):
    return c.post("/documents", files={"file": (name, xlsx(rows), "x")}, data={"deal": deal} if deal else {},
                  headers=h).json()["id"]


def fact(h, doc, value, row=1, metric="revenue", period="FY23"):
    r = c.post("/facts", headers=h, json={"entity": "A", "metric": metric, "period": period, "value": str(value),
                                          "unit": "USD", "document_id": doc, "page": 1,
                                          "quote": f"Sheet!B{row}: {value:,}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_conflicts_found_across_documents_with_rounding_flag_and_rejection():
    h = new_tenant(c, "cf1")
    d1 = up(h, [("rev", 1000), ("ebitda", 200)], "cim.xlsx")
    d2 = up(h, [("rev", 1100), ("ebitda", 200)], "qoe.xlsx")
    d3 = up(h, [("rev", 1001)], "mgmt.xlsx")
    f1, f2 = fact(h, d1, 1000), fact(h, d2, 1100)
    fact(h, d1, 200, 2, "ebitda"), fact(h, d2, 200, 2, "ebitda")  # agree: no conflict
    out = c.get("/facts/conflicts", headers=h).json()
    assert len(out) == 1 and out[0]["metric"] == "revenue" and out[0]["likely_rounding"] is False
    assert out[0]["severity"] == "material" and out[0]["cross_document"] is True
    assert {d["filename"] for x in out[0]["sources"] for d in x["documents"]} == {"cim.xlsx", "qoe.xlsx"}
    assert all(d["quote"] for x in out[0]["sources"] for d in x["documents"])
    assert out[0]["spread_pct"] == "9.09" and {v["fact_id"] for v in out[0]["values"]} == {f1, f2}
    f3 = fact(h, d3, 1001)
    assert len(c.get("/facts/conflicts", headers=h).json()[0]["values"]) == 3
    c.post(f"/facts/{f2}/review", headers=h, json={"action": "reject"})
    out = c.get("/facts/conflicts", headers=h).json()
    assert out[0]["severity"] == "rounding"
    assert out[0]["likely_rounding"] is True and {v["fact_id"] for v in out[0]["values"]} == {f1, f3}


def test_conflicts_respect_walls():
    t = c.post("/admin/tenants", json={"name": "cf2"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}
    k = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"deals": ["alpha"]}, headers=ADMIN).json()
    walled = {"Authorization": f"Bearer {k['api_key']}"}
    d1, d2 = up(owner, [("rev", 1000)], "a.xlsx", "alpha"), up(owner, [("rev", 1100)], "b.xlsx", "bravo")
    fact(owner, d1, 1000)
    fact(owner, d2, 1100)
    assert len(c.get("/facts/conflicts", headers=owner).json()) == 1
    assert c.get("/facts/conflicts", headers=walled).json() == []


def docx_bytes(t):
    d = Docx()
    d.add_paragraph(t)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def test_dd_seed_track_summary_and_walls():
    t = c.post("/admin/tenants", json={"name": "dd1"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}

    def key(**kw):
        return {"Authorization": "Bearer " + c.post(f"/admin/tenants/{t['tenant_id']}/keys", json=kw,
                                                       headers=ADMIN).json()["api_key"]}
    walled, viewer = key(deals=["alpha"]), key(role="viewer")
    n = c.post("/dd/requests/seed", json={"deal": "alpha", "categories": ["tax", "hr"]}, headers=owner).json()["created"]
    assert n == 6
    assert c.post("/dd/requests/seed", json={"deal": "alpha", "categories": ["tax", "hr"]}, headers=owner).json()["created"] == 0
    assert c.post("/dd/requests/seed", json={"deal": "alpha", "categories": ["zzz"]}, headers=owner).status_code == 422
    assert c.post("/dd/requests/seed", json={"deal": "bravo"}, headers=walled).status_code == 403
    assert c.post("/dd/requests/seed", json={"deal": "alpha"}, headers=viewer).status_code == 403
    rows = c.get("/dd/requests", params={"deal": "alpha"}, headers=walled).json()
    assert len(rows) == 6 and c.get("/dd/requests", headers=viewer).status_code == 200
    doc = c.post("/documents", files={"file": ("tax.docx", docx_bytes("tax returns FY23"), "x")},
                 data={"deal": "alpha"}, headers=owner).json()["id"]
    other = c.post("/documents", files={"file": ("x.docx", docx_bytes("bravo stuff"), "x")},
                   data={"deal": "bravo"}, headers=owner).json()["id"]
    tax = next(r for r in rows if r["category"] == "tax")
    assert c.patch(f"/dd/requests/{tax['id']}", json={"document_id": other}, headers=owner).status_code == 422
    r = c.patch(f"/dd/requests/{tax['id']}", json={"document_id": doc, "note": "FY21-23"}, headers=owner).json()
    assert r["status"] == "received" and r["document_id"] == doc
    assert c.patch(f"/dd/requests/{rows[1]['id']}", json={"status": "waived"}, headers=walled).json()["status"] == "waived"
    assert c.patch(f"/dd/requests/{rows[2]['id']}", json={"status": "bogus"}, headers=owner).status_code == 422
    s = c.get("/dd/summary", params={"deal": "alpha"}, headers=owner).json()
    assert s["total"] == 6 and s["closed"] == 2 and s["pct_complete"] == 33.3 and len(s["missing"]) == 4
    assert c.get("/dd/summary", params={"deal": "bravo"}, headers=walled).status_code == 404
    other_t = new_tenant(c, "dd2")
    assert c.patch(f"/dd/requests/{tax['id']}", json={"note": "x"}, headers=other_t).status_code == 404
    assert c.get("/dd/requests", headers=other_t).json() == []


def test_cross_document_only_drops_same_document_conflicts():
    h = new_tenant(c, "cf2")
    d1 = up(h, [("rev", 1000), ("ebitda", 200), ("ebitda", 250)], "cim.xlsx")
    d2 = up(h, [("rev", 1100)], "qoe.xlsx")
    fact(h, d1, 1000), fact(h, d2, 1100)
    fact(h, d1, 200, 2, "ebitda"), fact(h, d1, 250, 3, "ebitda")  # same document disagrees
    assert len(c.get("/facts/conflicts", headers=h).json()) == 2
    out = c.get("/facts/conflicts?cross_document_only=true", headers=h).json()
    assert [x["metric"] for x in out] == ["revenue"] and out[0]["cross_document"] is True
