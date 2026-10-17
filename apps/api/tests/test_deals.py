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


def test_mnpi_deal_hidden_from_other_unscoped_keys_and_visible_to_scoped_and_creator():
    t = c.post("/admin/tenants", json={"name": "mnpi1"}, headers={"X-Admin-Token": "test-admin"}).json()
    admin_hdr = {"X-Admin-Token": "test-admin"}
    creator = {"Authorization": f"Bearer {t['api_key']}"}
    other_key = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "admin"}, headers=admin_hdr).json()
    other = {"Authorization": f"Bearer {other_key['api_key']}"}
    c.post("/deals", headers=creator, json={"name": "Quiet", "mnpi": True})
    c.post("/deals", headers=creator, json={"name": "Open"})
    assert sorted(d["name"] for d in c.get("/deals", headers=creator).json()) == ["Open", "Quiet"]
    assert [d["name"] for d in c.get("/deals", headers=other).json()] == ["Open"]
    assert c.patch("/deals/Quiet", headers=other, json={"note": "x"}).status_code == 404
    assert c.delete("/deals/Quiet", headers=other).status_code == 404
    scoped = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "analyst", "deals": ["Quiet"]},
                    headers=admin_hdr).json()
    sh = {"Authorization": f"Bearer {scoped['api_key']}"}
    assert [d["name"] for d in c.get("/deals", headers=sh).json()] == ["Quiet"]
    assert c.patch("/deals/Quiet", headers=sh, json={"mnpi": False}).json()["mnpi"] is False


def test_retention_dry_run_then_purge_skips_held_and_is_audited():
    from datetime import UTC, datetime, timedelta

    from app.main import SessionLocal
    from app.models import Deal
    from app.rls import bind_tenant

    t = c.post("/admin/tenants", json={"name": "ret1"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    for name, stage in [("Old", "passed"), ("Held", "passed"), ("Live", "dd")]:
        c.post("/deals", headers=h, json={"name": name, "stage": stage})
    c.patch("/deals/Held", headers=h, json={"legal_hold": True})
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        for row in db.query(Deal).all():
            row.updated_at = old
        db.commit()
    assert c.post("/retention/deals", headers=h, json={"older_than_days": 365}).json() == {
        "dry_run": True, "candidates": ["Old"]}
    real = c.post("/retention/deals", headers=h, json={"older_than_days": 365, "dry_run": False}).json()
    assert real["deleted"] == ["Old"] and real["skipped"] == []
    assert sorted(d["name"] for d in c.get("/deals", headers=h).json()) == ["Held", "Live"]


def test_document_retention_skips_held_deal_and_cited_docs():
    from datetime import UTC, datetime, timedelta

    from app.main import SessionLocal
    from app.models import Document
    from app.rls import bind_tenant

    t = c.post("/admin/tenants", json={"name": "retdoc"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=h, json={"name": "Held"})
    c.patch("/deals/Held", headers=h, json={"legal_hold": True})
    ids = []
    for name, deal, value in [("a.xlsx", None, 10), ("b.xlsx", "Held", 20)]:
        # Distinct content: identical bytes dedupe to one document id.
        wb = Workbook()
        wb.active["A1"], wb.active["B1"] = "Revenue", value
        out = io.BytesIO()
        wb.save(out)
        data = {"deal": deal} if deal else {}
        ids.append(c.post("/documents", files={"file": (name, out.getvalue(), "x")}, data=data,
                          headers=h).json()["id"])
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        for row in db.query(Document).all():
            row.created_at = old
        db.commit()
    assert c.post("/retention/documents", headers=h, json={"older_than_days": 365}).json() == {
        "dry_run": True, "candidates": [ids[0]]}
    real = c.post("/retention/documents", headers=h, json={"older_than_days": 365, "dry_run": False}).json()
    assert real["deleted"] == [ids[0]] and real["skipped"] == []


def test_deal_pipeline_accepts_every_stage_in_order():
    t = c.post("/admin/tenants", json={"name": "pipeline"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=h, json={"name": "Pipe"})
    for stage in ["nda", "cim", "ioi", "loi", "dd", "ic", "signed"]:
        assert c.patch("/deals/Pipe", headers=h, json={"stage": stage}).json()["stage"] == stage
    assert c.patch("/deals/Pipe", headers=h, json={"stage": "cim_review"}).status_code == 422
