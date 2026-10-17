from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.lp_waterfall import Flow, Terms, american, per_lp, run
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
T = Terms(Decimal("0.08"), Decimal("0.20"), Decimal(1), "LPA s.5.1")


def test_full_catch_up_gives_gp_exactly_carry_on_profit():
    r = run([Flow(date(2020, 1, 1), Decimal(1000), "c1")], [Flow(date(2024, 1, 1), Decimal(1800), "d1")], T)
    t = r.totals
    assert t.to_lp_capital == 1000 and t.gp() == Decimal("160.00")  # 20% of the 800 profit
    assert t.lp() + t.gp() == Decimal(1800)


def test_partial_distribution_stays_in_pref_tier():
    r = run([Flow(date(2020, 1, 1), Decimal(1000), "c1")], [Flow(date(2021, 1, 1), Decimal(500), "d1")], T)
    assert r.totals.to_lp_capital == 500 and r.totals.gp() == 0 and r.totals.to_lp_pref == 0


def test_two_distributions_add_up_and_gp_carry_holds():
    r = run([Flow(date(2020, 1, 1), Decimal(1000), "c1")],
            [Flow(date(2021, 1, 1), Decimal(100), "d1"), Flow(date(2025, 1, 1), Decimal(2000), "d2")], T)
    assert r.totals.lp() + r.totals.gp() == Decimal(2100)
    assert r.totals.gp() == Decimal("220.00")  # 20% of the 1,100 profit once the catch-up is complete


def test_american_runs_each_deal_separately_and_per_lp_adds_up():
    deals = {"A": ([Flow(date(2020, 1, 1), Decimal(1000), "c")], [Flow(date(2024, 1, 1), Decimal(1800), "d")]),
             "B": ([Flow(date(2021, 1, 1), Decimal(500), "c")], [Flow(date(2022, 1, 1), Decimal(300), "d")])}
    res = american(deals, T)
    assert res["B"].totals.gp() == 0 and res["A"].totals.gp() == Decimal("160.00")
    total = Decimal(0)
    for r in res.values():
        total += r.totals.lp()
    shares = per_lp(sum_tiers(res), {"X": Decimal(1), "Y": Decimal(2)})
    assert sum(shares.values()) == total


def sum_tiers(res):
    from app.lp_waterfall import Tiers

    t = Tiers()
    for r in res.values():
        t.add(r.totals)
    return t


def test_terms_and_inputs_refused():
    with pytest.raises(ValueError):
        Terms(Decimal("0.08"), Decimal("0.2"), Decimal("0.1"), "x")  # catch-up below carry
    with pytest.raises(ValueError):
        run([], [Flow(date(2020, 1, 1), Decimal(-5), "d")], T)


def test_endpoint_european_and_per_lp():
    h = new_tenant(c, "wf1")
    body = {"terms": {"hurdle": "0.08", "carry": "0.2", "catchup": "1", "source": "LPA s.5.1"},
            "contributions": [{"on": "2020-01-01", "amount": "1000", "source": "call1"}],
            "distributions": [{"on": "2024-01-01", "amount": "1800", "source": "dist1"}],
            "commitments": {"A": {"value": "600", "source": "lpa-A"}, "B": {"value": "400", "source": "lpa-B"}}}
    j = c.post("/waterfall/lp", headers=h, json=body).json()
    assert j["totals"]["to_gp_catchup"] == "90.19" and sum(float(v["lp_proceeds"]) for v in j["per_lp"].values()) == 1640
    bad = c.post("/waterfall/lp", headers=h, json={**body, "terms": {**body["terms"], "catchup": "0.1"}})
    assert bad.status_code == 422


def test_escrow_holds_back_share_and_releases_later():
    from datetime import date as d

    from app.lp_waterfall import Escrow, hold_back

    now, later = hold_back([Flow(d(2024, 1, 1), Decimal(1000), "sale")], Escrow(Decimal("0.10"), 366, "LPA s.4"))
    assert now[0].amount == Decimal(900) and later[0].amount == Decimal(100)
    assert later[0].on == d(2025, 1, 1) and "escrow" in later[0].source


def test_clawback_returns_carry_above_carry_owed_on_fund_profit():
    from app.lp_waterfall import american, clawback

    c = {"A": ([Flow(date(2020, 1, 1), Decimal(1000), "c")], [Flow(date(2024, 1, 1), Decimal(1800), "d")]),
         "B": ([Flow(date(2021, 1, 1), Decimal(1000), "c")], [Flow(date(2022, 1, 1), Decimal(500), "d")])}
    res = american(c, T)
    assert res["A"].totals.gp() == Decimal("160.00") and res["B"].totals.gp() == 0
    cb = clawback([f for v in c.values() for f in v[0]], [f for v in c.values() for f in v[1]], res, T)
    assert cb.gp_received == Decimal("160.00") and cb.target == Decimal("60.00") and cb.amount == Decimal("100.00")


def test_endpoint_american_with_escrow_and_clawback():
    h = new_tenant(c, "wf2")
    body = {"mode": "american", "clawback": True,
            "terms": {"hurdle": "0.08", "carry": "0.2", "catchup": "1", "source": "LPA s.5.1"},
            "escrow": {"pct": "0.1", "days": 365, "source": "LPA s.4.2"},
            "deals": [
                {"name": "A", "contributions": [{"on": "2020-01-01", "amount": "1000", "source": "c1"}],
                 "distributions": [{"on": "2024-01-01", "amount": "1800", "source": "d1"}]},
                {"name": "B", "contributions": [{"on": "2021-01-01", "amount": "1000", "source": "c2"}],
                 "distributions": [{"on": "2022-01-01", "amount": "500", "source": "d2"}]}]}
    j = c.post("/waterfall/lp", headers=h, json=body).json()
    assert j["clawback"]["returned_to_lps"] == "100.00"
