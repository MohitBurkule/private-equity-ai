from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Document, Fact, PageRow
from app.rls import bind_tenant

c = TestClient(app)
# Verbatim from XPO_Ex10-2_TermLoanA_Agreement_2026-06.htm (sections 7.11(c) and the total leverage test).
PAGE_4 = ("(c) Borrower shall not permit the Interest Coverage Ratio to be less than 2.00:1.00 on and as of "
          "the last day of any Fiscal Quarter. "
          "Borrower shall not permit the Consolidated Total Net Leverage Ratio to be greater than 4.00:1.00 on "
          "and as of the last day of any Fiscal Quarter.")
# Verbatim from the same file. It states a dollar amount but does not name the Term Loan A facility, so no
# tranche fact may be stored from it.
PAGE_GRID = ("Applicable Margin Pricing Level Consolidated Total Net Leverage Ratio Term SOFR Margin (for Term "
             "SOFR Loans) Base Rate Margin (for Base Rate Loans) 1 >2.00:1.00 1.25 % 0.25 % 2 ≤2.00:1.00 1.125 % "
             "0.125 %")
PAGE_1 = ("Borrower has requested that the Lenders extend credit to Borrower in the form of Loans in an aggregate "
          "principal amount not to exceed $500,000,000, and the Lenders are willing to do so on the terms and "
          "conditions set forth herein")


def _seed(tenant_id: str, doc_id: str) -> None:
    with SessionLocal() as db:
        bind_tenant(db, tenant_id)
        d = Document(id=doc_id, tenant_id=tenant_id, sha256=doc_id, filename="xpo_tla.htm", n_pages=2, kind="pdf")
        d.pages = [PageRow(number=1, text=PAGE_1), PageRow(number=4, text=PAGE_4), PageRow(number=5, text=PAGE_GRID)]
        db.add(d)
        db.commit()


def test_credit_agreement_covenants_stored_and_unnamed_facility_not_stored():
    t = c.post("/admin/tenants", json={"name": "credit"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    doc_id = uuid4().hex * 2
    _seed(t["tenant_id"], doc_id)
    r = c.post(f"/documents/{doc_id}/credit-agreement/facts", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["skipped"] == [] and len(body["created"]) == 6
    assert body["maturity_clauses"] == []
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        facts = {f.metric: f for f in db.query(Fact).filter(Fact.id.in_(body["created"])).all()}
        lev = facts["covenant total_net_leverage maximum"]
        assert lev.value == Decimal("4.00") and lev.sources[0].page == 4 and lev.unit == "x"
        assert facts["covenant interest_coverage minimum"].value == Decimal("2.00")
        assert not any(m.startswith("facility amount") for m in facts)
        sofr = facts["Term SOFR margin level 2 (≤2.00:1.00)"]
        assert sofr.value == Decimal("1.125") and sofr.unit == "%" and sofr.sources[0].page == 5
        assert facts["Base Rate margin level 1 (>2.00:1.00)"].value == Decimal("0.25")
