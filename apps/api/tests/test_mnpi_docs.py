import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.audit import AuditEvent
from app.main import SessionLocal, app
from app.rls import bind_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def xlsx():
    wb = Workbook()
    wb.active["A1"], wb.active["B1"] = "Revenue", 10
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def unscoped_key(tenant_id: str) -> dict:
    key = c.post(f"/admin/tenants/{tenant_id}/keys", json={"role": "admin"}, headers=ADMIN).json()["api_key"]
    return {"Authorization": f"Bearer {key}"}


def test_mnpi_document_hidden_from_other_unscoped_keys_and_audited_for_creator():
    t = c.post("/admin/tenants", json={"name": "mnpidoc"}, headers=ADMIN).json()
    creator = {"Authorization": f"Bearer {t['api_key']}"}
    other = unscoped_key(t["tenant_id"])
    c.post("/deals", headers=creator, json={"name": "Secret", "mnpi": True})
    doc = c.post("/documents", files={"file": ("s.xlsx", xlsx(), "x")}, data={"deal": "Secret"},
                 headers=creator).json()["id"]
    assert c.get(f"/documents/{doc}/pages/1", headers=other).status_code == 404
    assert [d["id"] for d in c.get("/documents", headers=other).json()] == []
    assert [d["id"] for d in c.get("/documents", headers=creator).json()] == [doc]
    assert c.get(f"/documents/{doc}/pages/1", headers=creator).status_code == 200
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        actions = {e.action for e in db.query(AuditEvent).all()}
    assert "document.mnpi_access" in actions
    assert c.get("/audit/verify", headers=creator).json()["ok"] is True
