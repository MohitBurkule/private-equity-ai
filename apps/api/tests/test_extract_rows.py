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
                      json={"schema_name": schema, "period": "FY24"}).json()
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
