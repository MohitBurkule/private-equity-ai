from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import html_doc
from app.db import Base, make_engine
from app.facts import CitationError, add_html_fact
from app.main import app
from app.models import Document, HtmlUnit
from tests.helpers import new_tenant

# Shaped like the EDGAR exhibit: numbered headings, a table of contents that repeats the numbers with page
# figures, a defined term that points at a section, and a sentence that states the amount without naming the
# facility. Verbatim sentences from XPO_Ex10-2_TermLoanA_Agreement_2026-06.htm.
HTML = """<html><body>
<p>INDEX</p><p>2.1. Term Loan A Facility 59 2.2. Maturity and Repayment of Loans 61</p>
<p>WHEREAS, Borrower has requested that the Lenders extend credit to Borrower in the form of Loans in an aggregate principal amount not to exceed $500,000,000, and the Lenders are willing to do so.</p>
<p>1.1.&#8239;Definitions&#8239;.</p>
<p>“&#8239;Loans&#8239;” means the loans made by the Lenders to Borrower pursuant to Section 2.1(a)(i)&#8239;.</p>
<p>“ Material Adverse Effect ” means a material adverse effect on the business.</p>
<p>2.1.&#8239;Term Loan A Facility&#8239;.</p>
<p>(a) Subject to the terms hereof, each Lender severally agrees to make Loans on the Closing Date.</p>
<p>7.12. Financial Covenants.</p>
<table><tr><td>(c)</td><td>Borrower shall not permit the Interest Coverage Ratio to be less than 2.00:1.00 on and as of the last day of any Fiscal Quarter.</td></tr></table>
<p id="ccr">Borrower shall not permit the Consolidated Total Net Leverage Ratio to be greater than 4.00:1.00 on and as of the last day of any Fiscal Quarter.</p>
</body></html>
"""


def _units():
    return html_doc.parse_units(HTML.encode())


def test_blocks_carry_section_heading_offset_and_anchor():
    units = _units()
    cov = next(u for u in units if "Consolidated Total Net Leverage" in u.text)
    assert cov.section == "7.12" and cov.heading == "Financial Covenants"
    assert cov.anchor == "ccr"
    assert units[0].offset == 0 and units[1].offset > units[0].offset
    assert all(u.text == u.text.strip() and " " not in u.text for u in units)


def test_defined_term_resolves_to_facility_through_its_section():
    units = _units()
    defs = html_doc.defined_terms(units)
    chain = html_doc.resolve_defined_facility(units, "Loans", defs)
    assert chain["facility"] == "Term Loan A"
    # The TOC repeats "2.1. Term Loan A Facility 59"; the body heading ends with a full stop and is the one cited.
    assert chain["sources"][1][1] == "2.1. Term Loan A Facility ."


def test_amount_sentence_with_defined_term_cites_both_sentences():
    units = _units()
    found = html_doc.defined_facility_amounts(units)
    assert len(found) == 1
    f = found[0]
    assert f["facility"] == "Term Loan A" and f["amount"] == "500000000"
    assert f["quote"].startswith("WHEREAS") and f["extra_sources"][0][1].startswith("“ Loans ” means")


def test_unresolved_term_is_not_guessed():
    units = html_doc.parse_units("<p>“ Loans ” means the loans made by the Lenders.</p>"
                                 "<p>Loans aggregate principal amount not to exceed $5,000,000.</p>".encode())
    assert html_doc.defined_facility_amounts(units) == []


def test_html_fact_gate_checks_quote_in_its_own_block():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    units = _units()
    with Session(engine) as s:
        s.add(Document(id="h" * 64, tenant_id="t", sha256="h", filename="tla.htm", n_pages=0, kind="html"))
        s.flush()
        s.add_all(HtmlUnit(tenant_id="t", document_id="h" * 64, idx=u.idx, section=u.section, heading=u.heading,
                           anchor=u.anchor, offset=u.offset, text=u.text) for u in units)
        s.flush()
        cov = next(u for u in units if "Consolidated Total Net Leverage" in u.text)
        kw = {"tenant_id": "t", "entity": "XPO", "metric": "covenant total_net_leverage maximum",
              "period": "per agreement", "unit": "x", "document_id": "h" * 64}
        fact = add_html_fact(s, value=Decimal("4.00"), sources=[(cov.idx, "greater than 4.00:1.00")], **kw)
        src = fact.sources[0]
        assert (src.page, src.section, src.anchor, src.offset) == (0, "7.12", "ccr", cov.offset)
        with pytest.raises(CitationError):
            add_html_fact(s, value=Decimal("4.00"), sources=[(cov.idx, "less than 4.00:1.00")], **kw)
        with pytest.raises(CitationError):
            add_html_fact(s, value=Decimal("5.00"), sources=[(cov.idx, "greater than 4.00:1.00")], **kw)
        with pytest.raises(CitationError):
            add_html_fact(s, value=Decimal("4.00"), sources=[(999, "4.00")], **kw)


def test_html_upload_and_credit_endpoint_end_to_end():
    c = TestClient(app)
    h = new_tenant(c, "html-credit")
    r = c.post("/documents", files={"file": ("tla.htm", HTML.encode(), "text/html")}, headers=h)
    assert r.status_code == 200, r.text
    doc_id = r.json()[0]["id"] if isinstance(r.json(), list) else r.json()["id"]
    r = c.post(f"/documents/{doc_id}/credit-agreement/facts", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["skipped"] == []
    assert len(body["created"]) == 3


REAL = Path("/mnt/project-files/data/edgar/filings/XPO_Ex10-2_TermLoanA_Agreement_2026-06.htm")


@pytest.mark.skipif(not REAL.exists(), reason="XPO exhibit not mounted")
def test_real_term_loan_a_exhibit_resolves_loans_to_500m():
    units = html_doc.parse_units(REAL.read_bytes())
    found = html_doc.defined_facility_amounts(units)
    assert [(f["facility"], f["amount"]) for f in found] == [("Term Loan A", "500000000")]
    assert found[0]["extra_sources"][1][1] == "2.1. Term Loan A Facility."
