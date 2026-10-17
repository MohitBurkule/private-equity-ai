from decimal import Decimal

from app.acl import Principal
from app.agent import Ctx, _facts
from app.models import Fact, FactSource
from tests.test_facts_memo import setup_db


def test_agent_list_facts_skips_unreviewed_ocr_facts():
    s, doc = setup_db()
    s.add(Fact(tenant_id="t", entity="Acme", metric="revenue", period="FY24", value=Decimal(1000),
               unit="USD", status="verified", sources=[FactSource(document_id=doc, page=1, quote="Total revenues 1,000")]))
    s.add(Fact(tenant_id="t", entity="Acme", metric="net income", period="FY24", value=Decimal(150),
               unit="USD", status="ocr_unverified", sources=[FactSource(document_id=doc, page=1, quote="Net income 150")]))
    s.commit()
    who = Principal(tenant="t", role="analyst", deals=None, key_id="k")
    rows = _facts(Ctx(db=s, who=who))
    assert [r["metric"] for r in rows] == ["revenue"]
