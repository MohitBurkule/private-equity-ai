"""Floating-rate principal from the debt note, cited to its sentence, and the rate-move watcher run on it.
The XPO excerpt is verbatim from the FY2025 10-K (Item 7A). The EBITDA, interest and covenant threshold in the
watcher test are NOT from that excerpt: EBITDA is operating income 656 + D&A 521 (USD m, from the same 10-K), and
the 5.2x minimum is an assumed test threshold, labelled as such."""
import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import debt_parse
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
EXCERPT = (Path(__file__).parent / "fixtures" / "debt" / "xpo_fy2025_10k_rate_risk_excerpt.txt").read_text()
SENTENCE = ("As of December 31, 2025, we had an aggregate principal amount outstanding of $985 million on our "
            "Term Loan Facility")


def test_outstanding_sentence_is_read_in_full_usd_and_cited():
    rows = debt_parse.floating_principal([(41, EXCERPT)])
    assert rows == [{"facility": "Term Loan Facility", "as_of": "December 31, 2025", "amount": 985_000_000,
                     "page": 41, "quote": SENTENCE}]


def test_commitments_and_averages_are_not_taken_as_outstanding():
    text = ("the Lenders are willing to extend credit in an aggregate principal amount not to exceed $500,000,000. "
            "Assuming an average annual aggregate principal amount outstanding of $985 million, a hypothetical 1% "
            "increase would cost $10 million.")
    assert debt_parse.floating_principal([(1, text)]) == []


def test_term_b_names_are_read_as_facilities():
    found = debt_parse.extract([(3, "The Term B-4 Loans principal amount is $385,000,000.")])
    assert [f["facility"] for f in found] == ["Term B-4 Loans"]
    assert found[0]["amount"] == 385_000_000


def test_watcher_on_cited_xpo_inputs_alerts_when_cover_breaks_under_shock():
    h = new_tenant(c, "xpo1")
    wb = Workbook()
    rows = [("EBITDA", 1177), ("Interest", 219), ("Floating", 985), ("Min ICR (assumed test threshold)", 5.2)]
    for i, (k, v) in enumerate(rows, 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"] = k, v
    wb.active["A5"] = SENTENCE  # the 10-K sentence, pasted as a cited note in the workbook
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("xpo.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]

    def fact(metric, row, value, unit, quote, scale=1):
        # Stored value is the printed number times scale: USD millions in the quotes, a plain ratio for the test.
        r = c.post("/facts", headers=h, json={"entity": "XPO", "metric": metric, "period": "FY2025",
                                              "value": str(value), "unit": unit, "document_id": doc, "page": 1,
                                              "quote": quote, "scale": scale})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    co = c.post("/portfolio/companies", json={"name": "XPO"}, headers=h).json()["id"]
    fact("ebitda", 1, 1_177_000_000, "USD", "Sheet!B1: 1,177", scale=1_000_000)
    fact("interest_expense", 2, 219_000_000, "USD", "Sheet!B2: 219", scale=1_000_000)
    fl = fact("floating_rate_debt", 5, 985_000_000, "USD", f"Sheet!A5: {SENTENCE}", scale=1_000_000)
    thr = fact("debt.min_interest_cover_x", 4, 5.2, "x", "Sheet!B4: 5.2")
    c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "interest_coverage", "operator": ">=",
                                                         "threshold_fact_id": thr}, headers=h)
    made = [a for a in c.post("/alerts/scan", headers=h).json()["created"] if a["kind"] == "covenant_scenario"]
    # 1177/219 = 5.37x today (passes 5.2x); +100bp on 985 = +9.85: 1177/228.85 = 5.14x (breaks)
    assert len(made) == 1 and "5.14x" in made[0]["title"] and fl in made[0]["fact_ids"]
