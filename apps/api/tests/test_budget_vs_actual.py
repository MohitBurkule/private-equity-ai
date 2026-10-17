"""Budget against actual. Budget figures are cited observations kept apart from actuals: recording one never
supersedes an actual, and the variance is computed in code from the two cited figures."""
from decimal import Decimal

from app.portfolio import budget_variance
from tests.helpers import new_tenant
from tests.test_accounting_flow import _sync, c


def test_variance_is_actual_minus_budget_and_share_of_budget():
    diff, pct = budget_variance(Decimal(120), Decimal(100))
    assert diff == Decimal(20) and pct == Decimal(20)
    diff, pct = budget_variance(Decimal(80), Decimal(-100))
    assert diff == Decimal(180) and pct == Decimal(180)


def test_zero_budget_has_no_percentage():
    diff, pct = budget_variance(Decimal(5), Decimal(0))
    assert diff == Decimal(5) and pct is None


def test_budget_does_not_supersede_actual_and_is_listed_beside_it(monkeypatch):
    h = new_tenant(c, "budget-vs-actual")
    assert _sync(h, monkeypatch).status_code == 200
    co = next(x for x in c.get("/portfolio/submissions", params={"period": "2026-08"}, headers=h).json()["submitted"])["company_id"]
    kpis = c.get(f"/portfolio/companies/{co}/kpis", headers=h).json()
    rev = next(k for k in kpis if k["period"] == "2026-08" and k["metric"].lower().startswith("revenue"))
    # The same cited fact stands in as the budget here: the test covers the bookkeeping, not a plan figure.
    assert c.post(f"/portfolio/companies/{co}/observations?fact_id={rev['fact_id']}&kind=budget", headers=h).status_code == 201

    after = c.get(f"/portfolio/companies/{co}/kpis", headers=h).json()
    assert any(k["fact_id"] == rev["fact_id"] for k in after)  # the actual is still current

    body = c.get(f"/portfolio/companies/{co}/budget-vs-actual", params={"period": "2026-08"}, headers=h).json()
    row = next(m for m in body["metrics"] if m["metric"] == rev["metric"])
    assert row["actual"]["fact_id"] == row["budget"]["fact_id"] == rev["fact_id"]
    assert row["actual"]["source"] == "ACME-monthly.xlsx"  # every figure names the document it came from
    assert Decimal(row["variance"]) == 0 and Decimal(row["variance_pct"]) == 0
