from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Document, Fact, PageRow
from app.rls import bind_tenant

c = TestClient(app)
PAGE_4 = ("Section 7.11 Financial Covenants. The Borrower shall not permit the Total Net Leverage Ratio "
          "to be greater than 4.00 to 1.00. The Borrower shall not permit the Interest Coverage Ratio "
          "to be less than 2.00 to 1.00.")
PAGE_1 = ("The Lenders have agreed to provide Term Loan A Facility in an aggregate principal amount of "
          "$830,000,000 under this Agreement.")


def _seed(tenant_id: str, doc_id: str) -> None:
    with SessionLocal() as db:
        bind_tenant(db, tenant_id)
        d = Document(id=doc_id, tenant_id=tenant_id, sha256=doc_id, filename="xpo_tla.htm", n_pages=2, kind="pdf")
        d.pages = [PageRow(number=1, text=PAGE_1), PageRow(number=4, text=PAGE_4)]
        db.add(d)
        db.commit()


def test_credit_agreement_covenants_and_tranche_stored_as_cited_facts():
    t = c.post("/admin/tenants", json={"name": "credit"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    doc_id = uuid4().hex * 2
    _seed(t["tenant_id"], doc_id)
    r = c.post(f"/documents/{doc_id}/credit-agreement/facts", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["skipped"] == [] and len(body["created"]) == 3
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        facts = {f.metric: f for f in db.query(Fact).filter(Fact.id.in_(body["created"])).all()}
        lev = facts["covenant total_net_leverage maximum"]
        assert lev.value == Decimal("4.00") and lev.sources[0].page == 4 and lev.unit == "x"
        assert facts["covenant interest_coverage minimum"].value == Decimal("2.00")
        tla = facts["facility amount Term Loan A"]
        assert tla.value == Decimal(830000000) and tla.unit == "USD" and tla.sources[0].page == 1
        assert tla.status == "verified"
