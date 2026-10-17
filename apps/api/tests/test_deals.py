import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_deal_lifecycle_and_summary():
    h = new_tenant(c, "dl1")
    r = c.post("/deals", headers=h, json={"name": "Project Atlas"})
    assert r.status_code == 201 and r.json()["stage"] == "sourcing"
    assert c.post("/deals", headers=h, json={"name": "Project Atlas"}).status_code == 409
    assert c.post("/deals", headers=h, json={"name": "X", "stage": "bogus"}).status_code == 422
    assert c.post("/deals", headers=h, json={"name": "  "}).status_code == 422
    c.post("/dd/requests/seed", headers=h, json={"deal": "Project Atlas", "categories": ["legal"]})
    r = c.patch("/deals/Project Atlas", headers=h, json={"stage": "dd", "note": "kickoff"})
    assert r.json()["stage"] == "dd" and r.json()["dd_open"] == r.json()["dd_total"] > 0
    assert [d["name"] for d in c.get("/deals", headers=h).json()] == ["Project Atlas"]
    assert c.patch("/deals/nope", headers=h, json={"stage": "ic"}).status_code == 404


def test_deals_tenant_isolated():
    a, b = new_tenant(c, "dl2"), new_tenant(c, "dl3")
    c.post("/deals", headers=a, json={"name": "Secret"})
    assert c.get("/deals", headers=b).json() == []
    assert c.patch("/deals/Secret", headers=b, json={"stage": "ic"}).status_code == 404


def test_legal_hold_blocks_delete_until_lifted():
    h = new_tenant(c, "dl4")
    c.post("/deals", headers=h, json={"name": "Held"})
    assert c.patch("/deals/Held", headers=h, json={"legal_hold": True}).json()["legal_hold"] is True
    assert c.delete("/deals/Held", headers=h).status_code == 409
    c.patch("/deals/Held", headers=h, json={"legal_hold": False})
    assert c.delete("/deals/Held", headers=h).json()["deleted"] == "Held"
    assert c.get("/deals", headers=h).json() == []


def test_delete_removes_dd_items():
    h = new_tenant(c, "dl5")
    c.post("/deals", headers=h, json={"name": "Gone"})
    c.post("/dd/requests/seed", headers=h, json={"deal": "Gone", "categories": ["legal"]})
    r = c.delete("/deals/Gone", headers=h)
    assert r.status_code == 200 and r.json()["dd_requests_removed"] > 0
    assert c.delete("/deals/Gone", headers=h).status_code == 404


def test_delete_refuses_while_documents_linked_and_is_tenant_isolated():
    a, b = new_tenant(c, "dl6"), new_tenant(c, "dl7")
    c.post("/deals", headers=a, json={"name": "Linked"})
    assert c.delete("/deals/Linked", headers=b).status_code == 404
    buf = io.BytesIO()
    wb = Workbook()
    wb.active["A1"], wb.active["B1"] = "Revenue", 10
    wb.save(buf)
    assert c.post("/documents", files={"file": ("l.xlsx", buf.getvalue(), "x")}, data={"deal": "Linked"},
                  headers=a).status_code in (200, 201)
    assert c.delete("/deals/Linked", headers=a).status_code == 409


def test_mnpi_deal_hidden_from_unscoped_key_and_visible_to_scoped_key():
    t = c.post("/admin/tenants", json={"name": "mnpi1"}, headers={"X-Admin-Token": "test-admin"}).json()
    admin = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=admin, json={"name": "Quiet", "mnpi": True})
    c.post("/deals", headers=admin, json={"name": "Open"})
    assert [d["name"] for d in c.get("/deals", headers=admin).json()] == ["Open"]
    assert c.patch("/deals/Quiet", headers=admin, json={"note": "x"}).status_code == 404
    assert c.delete("/deals/Quiet", headers=admin).status_code == 404
    scoped = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "analyst", "deals": ["Quiet"]},
                    headers={"X-Admin-Token": "test-admin"}).json()
    sh = {"Authorization": f"Bearer {scoped['api_key']}"}
    assert [d["name"] for d in c.get("/deals", headers=sh).json()] == ["Quiet"]
    assert c.patch("/deals/Quiet", headers=sh, json={"mnpi": False}).json()["mnpi"] is False
    assert sorted(d["name"] for d in c.get("/deals", headers=admin).json()) == ["Open", "Quiet"]
