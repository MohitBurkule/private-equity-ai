"""Valuation marks and roll-forward. A mark is a cited figure kept apart from actuals. The change in value is
computed in code, and withheld whenever any of its four inputs is missing."""
from decimal import Decimal

from app.portfolio import roll_forward
from tests.helpers import new_tenant
from tests.test_accounting_flow import _sync, c


def test_change_in_value_is_closing_less_opening_less_cash_in_plus_cash_out():
    d = Decimal
    assert roll_forward(d(100), d(130), d(10), d(5)) == d(25)
    assert roll_forward(d(100), d(90), d(0), d(0)) == d(-10)


def test_any_missing_input_withholds_the_change():
    d = Decimal
    assert roll_forward(None, d(130), d(10), d(5)) is None
    assert roll_forward(d(100), d(130), None, d(5)) is None


def test_marks_are_listed_apart_from_actuals_and_roll_forward_cites_them(monkeypatch):
    h = new_tenant(c, "valuation-roll-forward")
    assert _sync(h, monkeypatch).status_code == 200
    co = next(x["company_id"] for x in c.get("/portfolio/submissions", params={"period": "2026-08"},
                                              headers=h).json()["submitted"])
    kpis = c.get(f"/portfolio/companies/{co}/kpis", headers=h).json()
    # ACME's trial balance gives revenue for both months. Revenue stands in as the mark here, since the test
    # ledger carries no equity value; the bookkeeping is what is under test.
    rev = {k["period"]: k for k in kpis if k["metric"] == "revenue_usd"}
    assert {"2026-08", "2026-09"} <= set(rev)
    for period in ("2026-08", "2026-09"):
        assert c.post(f"/portfolio/companies/{co}/observations?fact_id={rev[period]['fact_id']}&kind=mark",
                      headers=h).status_code == 201

    after = c.get(f"/portfolio/companies/{co}/kpis", headers=h).json()
    assert {k["fact_id"] for k in after} >= {rev["2026-08"]["fact_id"], rev["2026-09"]["fact_id"]}  # actuals stand

    body = c.get(f"/portfolio/companies/{co}/roll-forward",
                 params={"period": "2026-09", "prior": "2026-08", "mark_metric": "revenue_usd"},
                 headers=h).json()
    assert body["opening"]["fact_id"] == rev["2026-08"]["fact_id"]
    assert body["closing"]["fact_id"] == rev["2026-09"]["fact_id"]
    assert body["contributions"] is None and body["distributions"] is None
    assert body["change_in_value"] is None  # cash flows not on file, so no change is computed
