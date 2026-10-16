import io
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def upload(h, deal=None):
    wb = Workbook()
    wb.active["A1"] = "revenue"
    wb.active["B1"] = 1234
    wb.active["A2"] = "ebitda"
    wb.active["B2"] = 321
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, data={"deal": deal} if deal else {},
                  headers=h).json()["id"]


def mk(h, doc, metric="revenue", value="1234", quote="Sheet!B1: 1,234"):
    r = c.post("/facts", headers=h, json={"entity": "A", "metric": metric, "period": "FY", "value": value,
                                          "unit": "USD", "document_id": doc, "page": 1, "quote": quote})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_queue_listing_accept_reject_and_memo_effect():
    h = new_tenant(c, "rv1")
    doc = upload(h)
    f1, f2 = mk(h, doc), mk(h, doc, "ebitda", "321", "Sheet!B2: 321")
    assert [f["id"] for f in c.get("/facts", headers=h).json()] == [f1, f2]
    r = c.post(f"/facts/{f2}/review", headers=h, json={"action": "reject", "note": "wrong line"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["review_note"] == "wrong line"
    assert r.json()["reviewed_by"].startswith("key:")
    memo = c.get("/memo", params={"entity": "A"}, headers=h).json()["markdown"]
    assert "revenue" in memo and "ebitda" not in memo
    assert [f["id"] for f in c.get("/facts", params={"status": "rejected"}, headers=h).json()] == [f2]
    ok = c.post(f"/facts/{f2}/review", headers=h, json={"action": "accept"})
    assert ok.json()["status"] == "verified"


def test_edit_must_pass_the_same_gate_and_is_audited():
    h = new_tenant(c, "rv2")
    doc = upload(h)
    f = mk(h, doc)
    bad = c.post(f"/facts/{f}/review", headers=h, json={"action": "edit", "value": "999"})
    assert bad.status_code == 422
    bad2 = c.post(f"/facts/{f}/review", headers=h, json={"action": "edit", "quote": "not on the page"})
    assert bad2.status_code == 422
    good = c.post(f"/facts/{f}/review", headers=h, json={"action": "edit", "value": "321", "quote": "Sheet!B2: 321"})
    assert good.status_code == 200 and Decimal(good.json()["value"]) == 321
    assert good.json()["sources"][0]["quote"] == "Sheet!B2: 321"
    assert c.get("/audit/verify", headers=h).json()["ok"] is True
    assert c.post(f"/facts/{f}/review", headers=h, json={"action": "bogus"}).status_code == 422


def test_viewer_cannot_review_and_other_tenant_and_walls_get_404():
    admin = {"X-Admin-Token": "test-admin"}
    t = c.post("/admin/tenants", json={"name": "rv3"}, headers=admin).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}

    def key(**kw):
        return {"Authorization": "Bearer " + c.post(f"/admin/tenants/{t['tenant_id']}/keys", json=kw,
                                                       headers=admin).json()["api_key"]}
    doc = upload(owner, "bravo")
    f = mk(owner, doc)
    assert c.post(f"/facts/{f}/review", headers=key(role="viewer"), json={"action": "accept"}).status_code == 403
    assert c.post(f"/facts/{f}/review", headers=key(deals=["alpha"]), json={"action": "accept"}).status_code == 404
    assert c.get("/facts", headers=key(deals=["alpha"])).json() == []
    other = new_tenant(c, "rv4")
    assert c.post(f"/facts/{f}/review", headers=other, json={"action": "accept"}).status_code == 404
