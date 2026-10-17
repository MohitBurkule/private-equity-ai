from decimal import Decimal

from fastapi.testclient import TestClient

from app.facts import add_html_fact
from app.main import SessionLocal, app
from app.models import Document
from tests.helpers import new_tenant

c = TestClient(app)
HTML = """<html><body>
<p>7.12. Financial Covenants.</p>
<p id="ccr">Borrower shall not permit the Consolidated Total Net Leverage Ratio to be greater than 4.00:1.00.</p>
<p id="other">Borrower shall not permit the Interest Coverage Ratio to be less than 2.00:1.00.</p>
</body></html>"""


def test_reviewer_can_correct_an_html_fact_and_keeps_block_citation():
    h = new_tenant(c, "review-html")
    r = c.post("/documents", files={"file": ("ca.htm", HTML.encode(), "text/html")}, headers=h)
    doc = r.json()[0]["id"] if isinstance(r.json(), list) else r.json()["id"]
    with SessionLocal() as s:
        d = s.get(Document, doc)
        tenant = d.tenant_id
        fact = add_html_fact(s, tenant_id=tenant, entity="Co", metric="covenant total_net_leverage maximum",
                             period="per agreement", value=Decimal("4.00"), unit="x", document_id=doc,
                             sources=[(1, "greater than 4.00:1.00")])
        fid = fact.id
    # A quote from a different block fails the gate: the citation must stay in the cited block.
    out = c.post(f"/facts/{fid}/review", headers=h,
                 json={"action": "edit", "value": "2.00", "page": 1, "quote": "less than 2.00:1.00"})
    assert out.status_code == 422  # wrong block for that quote: the gate refuses
    out = c.post(f"/facts/{fid}/review", headers=h,
                 json={"action": "edit", "value": "4.00", "page": 1, "quote": "greater than 4.00:1.00"})
    assert out.status_code == 200, out.text
    src = out.json()["sources"][0]
    assert src["page"] == 0 and "7.12" in src["locator"] and "p.0" not in src["locator"]
    assert c.post(f"/facts/{fid}/review", headers=h, json={"action": "accept"}).json()["status"] == "verified"
