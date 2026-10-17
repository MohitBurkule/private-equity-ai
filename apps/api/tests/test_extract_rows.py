import io
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app, llm_dependency
from tests.helpers import new_tenant

c = TestClient(app)


class Fake:
    def __init__(self, rows):
        self.rows = rows

    def complete(self, system, prompt):
        return json.dumps({"rows": self.rows})


def upload(h, cells):
    wb = Workbook()
    for coord, v in cells.items():
        wb.active[coord] = v
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("t.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]


def run(h, doc, schema, rows):
    app.dependency_overrides[llm_dependency] = lambda: Fake(rows)
    try:
        return c.post(f"/documents/{doc}/extract-rows", headers=h,
                      json={"schema_name": schema, "period": "FY24", "entity": "Co"}).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)


def test_cap_table_rows_cited_and_gated():
    h = new_tenant(c, "rows1")
    doc = upload(h, {"A1": "Acme Holder", "B1": 1000, "A2": "Other Holder", "B2": 500})
    good = {"page": 1, "quote": "Sheet!B1: 1,000 | row: Acme Holder",
            "fields": {"holder": "Acme Holder", "share_class": "Ordinary", "shares": 1000}}
    off_page = {"page": 9, "quote": "Sheet!B1: 1,000", "fields": good["fields"]}
    no_number = {"page": 1, "quote": "Sheet!B1: 1,000 | row: Acme Holder",
                 "fields": {"holder": "Acme Holder", "share_class": "Ordinary", "shares": 77}}
    negative = {"page": 1, "quote": "Sheet!B1: 1,000 | row: Acme Holder",
                "fields": {"holder": "Acme Holder", "share_class": "Ordinary", "shares": -5}}
    out = run(h, doc, "cap_table", [good, off_page, no_number, negative])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected", "rejected", "rejected"]
    assert out["rows"][1]["reason"] == "cited page not found"
    assert "not printed" in out["rows"][2]["reason"]
    facts = c.get("/facts", headers=h).json()
    shares = [f for f in facts if f["metric"] == "shares Ordinary"]
    assert len(shares) == 1 and shares[0]["status"] == "auto" and shares[0]["entity"] == "Acme Holder"


def test_contract_flags_need_only_quote_on_page():
    h = new_tenant(c, "rows2")
    doc = upload(h, {"A1": "Change of control: Beta Ltd may terminate on a merger.",
                     "A2": "Exclusivity applies to Beta Ltd.", "B3": 30})
    out = run(h, doc, "contract_terms", [{
        "page": 1, "quote": "Sheet!A1: Change of control: Beta Ltd may terminate on a merger.",
        "fields": {"counterparty": "Beta Ltd", "change_of_control": True, "exclusivity": True}}])
    assert out["rows"][0]["status"] == "accepted" and len(out["rows"][0]["fact_ids"]) == 2
    bad = run(h, doc, "contract_terms", [{"page": 1, "quote": "Sheet!A1: not on this page",
                                          "fields": {"counterparty": "Beta Ltd", "mfn": True}}])
    assert bad["rows"][0]["reason"] == "quote not found on cited page"


def test_unknown_schema_is_refused():
    h = new_tenant(c, "rows3")
    doc = upload(h, {"A1": "x"})
    app.dependency_overrides[llm_dependency] = lambda: Fake([])
    try:
        r = c.post(f"/documents/{doc}/extract-rows", headers=h, json={"schema_name": "debt", "period": "FY24"})
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert r.status_code == 422


def test_customer_concentration_rows_keep_their_own_period():
    h = new_tenant(c, "rows4")
    doc = upload(h, {"A1": "Acme Corp", "B1": "12.5%", "C1": "FY23"})
    good = {"page": 1, "quote": "Sheet!B1: 12.5% | row: Acme Corp",
            "fields": {"customer": "Acme Corp", "period": "FY24", "revenue_pct": 12.5}}
    over = {"page": 1, "quote": "Sheet!B1: 12.5% | row: Acme Corp",
            "fields": {"customer": "Acme Corp", "period": "FY24", "revenue_pct": 140}}
    out = run(h, doc, "customer_concentration", [good, over])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected"]
    facts = c.get("/facts", headers=h).json()
    pct = [f for f in facts if f["metric"] == "revenue_pct"]
    assert len(pct) == 1 and pct[0]["period"] == "FY24" and pct[0]["entity"] == "Acme Corp"


def test_ebitda_bridge_rows_keep_each_line_as_stated():
    h = new_tenant(c, "rows5")
    doc = upload(h, {"A1": "Reported EBITDA", "B1": 100, "C1": "FY24"})
    rep = {"page": 1, "quote": "Sheet!B1: 100 | row: Reported EBITDA",
           "fields": {"period": "FY24", "item": "Reported EBITDA", "kind": "reported", "amount": 100}}
    bad = {"page": 1, "quote": "Sheet!B1: 100 | row: Reported EBITDA",
           "fields": {"period": "FY24", "item": "Restructuring", "kind": "add_back", "amount": 7}}
    out = run(h, doc, "ebitda_bridge", [rep, bad])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected"]
    assert "not printed" in out["rows"][1]["reason"]
    facts = c.get("/facts", headers=h).json()
    assert [f["metric"] for f in facts if f["metric"].startswith("ebitda_bridge")] == ["ebitda_bridge reported"]


def test_bridge_recheck_flags_mismatch_and_keeps_stated_total():
    h = new_tenant(c, "rows6")
    doc = upload(h, {"A1": "EBITDA", "B1": 100, "C1": 20, "D1": 130, "E1": 120})
    q = "Sheet!{}1: {} | row: EBITDA"

    def line(col, num, kind, amount):
        return {"page": 1, "quote": q.format(col, num),
                "fields": {"period": "FY24", "item": kind, "kind": kind, "amount": amount}}

    bad = run(h, doc, "ebitda_bridge", [line("B", "100", "reported", 100), line("C", "20", "add_back", 20),
                                        line("D", "130", "adjusted", 130)])
    assert bad["bridge_checks"] == [{"period": "FY24", "expected": "120", "stated": "130",
                                     "difference": "-10", "status": "mismatch"}]
    good = run(h, doc, "ebitda_bridge", [line("B", "100", "reported", 100), line("C", "20", "add_back", 20),
                                         line("E", "120", "adjusted", 120)])
    assert good["bridge_checks"][0]["status"] == "match"


def test_bridge_mismatch_raises_one_inbox_item():
    h = new_tenant(c, "rows7")
    doc = upload(h, {"A1": "EBITDA", "B1": 100, "C1": 20, "D1": 130})
    q = "Sheet!{}1: {} | row: EBITDA"
    lines = [{"page": 1, "quote": q.format("B", "100"), "fields": {"period": "FY24", "item": "r", "kind": "reported", "amount": 100}},
             {"page": 1, "quote": q.format("C", "20"), "fields": {"period": "FY24", "item": "a", "kind": "add_back", "amount": 20}},
             {"page": 1, "quote": q.format("D", "130"), "fields": {"period": "FY24", "item": "t", "kind": "adjusted", "amount": 130}}]
    run(h, doc, "ebitda_bridge", lines)
    run(h, doc, "ebitda_bridge", lines)
    alerts = [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "bridge_mismatch"]
    assert len(alerts) == 1 and "does not re-add" in alerts[0]["title"]


def test_cohort_rows_keep_each_measure_and_reject_empty_rows():
    h = new_tenant(c, "rows8")
    doc = upload(h, {"A1": "2022 Q1 cohort", "B1": 1500000})
    q = "Sheet!{}1: {} | row: 2022 Q1 cohort"
    good = {"page": 1, "quote": q.format("B", "1,500,000"),
            "fields": {"cohort": "2022 Q1", "period": "FY24", "arr": 1500000}}
    empty = {"page": 1, "quote": q.format("B", "1,500,000"), "fields": {"cohort": "2022 Q1", "period": "FY24"}}
    out = run(h, doc, "cohort", [good, empty])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected"]
    metrics = sorted(f["metric"] for f in c.get("/facts", headers=h).json() if f["metric"].startswith("cohort_"))
    assert metrics == ["cohort_arr"]


HTML_FILING = """<html><body>
<p>3.2. Capitalization.</p>
<p>The following table sets out our shareholders and their holdings.</p>
<table><tr><td>Acme Holdings LLC</td><td>Class A common stock</td><td>1,000,000</td></tr></table>
<p id="ex">Borrower may not assign this agreement without consent. Termination requires 90 days notice.</p>
</body></html>"""


def test_html_filing_rows_cite_section_and_block_not_page():
    h = new_tenant(c, "rows10")
    r = c.post("/documents", files={"file": ("10k.htm", HTML_FILING.encode(), "text/html")}, headers=h)
    doc = r.json()[0]["id"] if isinstance(r.json(), list) else r.json()["id"]
    # Block 2 is the table row; its text is its cells joined by spaces.
    good = {"page": 2, "quote": "Acme Holdings LLC Class A common stock 1,000,000",
            "fields": {"holder": "Acme Holdings LLC", "share_class": "Class A common stock", "shares": 1000000}}
    wrong_block = {"page": 3, "quote": "Acme Holdings LLC Class A common stock 1,000,000",
                   "fields": good["fields"]}
    out = run(h, doc, "cap_table", [good, wrong_block])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected"]
    assert out["rows"][1]["reason"] == "quote not found on cited page"
    shares = [f for f in c.get("/facts", headers=h).json() if f["metric"] == "shares Class A common stock"]
    assert len(shares) == 1 and shares[0]["status"] == "auto"
    locator = shares[0]["sources"][0]["locator"]
    assert "3.2" in locator and "p.0" not in locator and "p." not in locator


def test_debt_schedule_rows_cite_principal_and_rate():
    h = new_tenant(c, "rows9")
    doc = upload(h, {"A1": "Term Loan A Lenders", "B1": 500000000, "C1": "5.25%"})
    good = {"page": 1, "quote": "Sheet!B1: 500,000,000 | row: Term Loan A Lenders",
            "fields": {"lender": "Agent Bank", "instrument": "term_loan", "principal": 500000000}}
    bad = {"page": 1, "quote": "Sheet!B1: 500,000,000 | row: Term Loan A Lenders",
           "fields": {"lender": "Agent Bank", "instrument": "bonds", "principal": 500000000}}
    out = run(h, doc, "debt_schedule", [good, bad])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected"]
    metrics = sorted(f["metric"] for f in c.get("/facts", headers=h).json() if f["metric"] in ("principal", "rate_pct"))
    assert metrics == ["principal"]


def test_covenant_rows_match_credit_agreement_metric_naming():
    h = new_tenant(c, "rows11")
    doc = upload(h, {"A1": "Interest Coverage Ratio", "B1": "2.00:1.00"})
    q = "Sheet!B1: 2.00:1.00 | row: Interest Coverage Ratio"
    good = {"page": 1, "quote": q,
            "fields": {"name": "Interest cover", "metric": "interest_cover", "operator": ">=", "threshold": 2.0}}
    no_number = {"page": 1, "quote": q,
                 "fields": {"name": "Interest cover", "metric": "interest_cover", "operator": ">=", "threshold": 3.5}}
    out = run(h, doc, "covenant", [good, no_number])
    assert [r["status"] for r in out["rows"]] == ["accepted", "rejected"]
    metrics = [f["metric"] for f in c.get("/facts", headers=h).json() if f["metric"].startswith("covenant ")]
    assert metrics == ["covenant interest_cover minimum"]
