from decimal import Decimal

from fastapi.testclient import TestClient

from app.factsxlsx import visible_facts
from app.main import SessionLocal, app
from app.models import Document, Fact, FactSource
from app.rls import bind_tenant

c = TestClient(app)


def _seed(tenant_id: str) -> int:
    with SessionLocal() as db:
        bind_tenant(db, tenant_id)
        db.add(Document(id="u" * 64, tenant_id=tenant_id, sha256="u", filename="cim.pdf", n_pages=1, kind="pdf"))
        db.flush()
        db.add(Fact(tenant_id=tenant_id, entity="Acme", metric="revenue", period="FY24", value=Decimal(1000),
                    unit="USD", status="verified", sources=[FactSource(document_id="u" * 64, page=1, quote="x")]))
        pending = Fact(tenant_id=tenant_id, entity="Acme", metric="ebitda", period="FY24", value=Decimal(90),
                       unit="USD", status="ocr_unverified",
                       sources=[FactSource(document_id="u" * 64, page=1, quote="y")])
        db.add(pending)
        db.commit()
        return pending.id


def test_excel_export_and_lbo_input_exclude_unverified_facts():
    t = c.post("/admin/tenants", json={"name": "unv"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    pending_id = _seed(t["tenant_id"])
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        metrics = {f.metric for f in visible_facts(db, t["tenant_id"], None, None)}
    assert metrics == {"revenue"}
    r = c.post("/lbo/returns", headers=h, json={"inputs": {"ebitda": {"fact_id": pending_id}}})
    assert r.status_code == 422
