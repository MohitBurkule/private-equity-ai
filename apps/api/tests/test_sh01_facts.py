from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Document, Fact, PageRow
from app.rls import bind_tenant
from tests.test_sh01 import P1, P2, P3

c = TestClient(app)


def _seed(tenant_id: str, doc_id: str) -> None:
    with SessionLocal() as db:
        bind_tenant(db, tenant_id)
        d = Document(id=doc_id, tenant_id=tenant_id, sha256=doc_id, filename="sh01.pdf", n_pages=3, kind="pdf")
        d.pages = [PageRow(number=i + 1, text=t) for i, t in enumerate([P1, P2, P3])]
        db.add(d)
        db.commit()


def test_sh01_allotment_stored_as_cited_fact_and_bad_quote_refused():
    t = c.post("/admin/tenants", json={"name": "sh01"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    doc_id = uuid4().hex * 2
    _seed(t["tenant_id"], doc_id)
    r = c.post(f"/documents/{doc_id}/capital-form/facts", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["created"]) == 1 and body["skipped"] == []
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        f = db.get(Fact, body["created"][0])
        assert f.value == Decimal(15000000) and f.unit == "shares" and f.entity == "09446231"
        assert f.period == "15/08/2025" and f.sources[0].page == 1
        assert f.status == "verified" and "15000000" in f.sources[0].quote
