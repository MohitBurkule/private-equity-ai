from datetime import date
from decimal import Decimal as D

import pytest

from app.fundmetrics import fund_metrics, vintage_cohorts, xirr


def test_irr_matches_closed_form_for_one_in_one_out():
    # 100 in on 2020-01-01, 121 out on 2022-01-01, both on actual/365 day counts
    days = (date(2022, 1, 1) - date(2020, 1, 1)).days
    expected = (121 / 100) ** (365 / days) - 1
    r, note = xirr([(date(2020, 1, 1), -100.0), (date(2022, 1, 1), 121.0)])
    assert note == "" and r == pytest.approx(expected, rel=1e-9)


def test_nav_only_fund_has_irr_from_nav_and_no_multiples_without_paid_in():
    m = fund_metrics([], D(50), date(2024, 1, 1))
    assert m.paid_in == 0 and m.dpi is None and m.rvpi is None and m.tvpi is None
    m = fund_metrics([(date(2020, 1, 1), D(-100))], D(150), date(2022, 1, 1))
    assert m.tvpi == D("1.5") and m.rvpi == D("1.5") and m.dpi == 0
    assert m.irr is not None and m.irr > 0


def test_cohort_median_is_none_when_one_fund_has_no_paid_in():
    as_of = date(2024, 1, 1)
    funds = [
        ("A", 2019, [(date(2019, 1, 1), D(-100))], D(200)),   # tvpi 2.0
        ("B", 2019, [], D(30)),                              # nothing paid in: tvpi None
    ]
    (c,) = vintage_cohorts(funds, as_of)
    assert c.funds == 2 and c.paid_in == 100
    assert c.pooled_tvpi == D("2.3")      # (0 + 230) / 100, money summed then divided
    assert c.median_tvpi is None          # one fund has no multiple, so no median is shown


def test_cohort_median_even_count_averages_middle_two():
    as_of = date(2024, 1, 1)
    funds = [("A", 2020, [(date(2020, 1, 1), D(-100))], D(100)),
             ("B", 2020, [(date(2020, 1, 1), D(-100))], D(200)),
             ("C", 2020, [(date(2020, 1, 1), D(-100))], D(300)),
             ("D", 2020, [(date(2020, 1, 1), D(-100))], D(500))]
    (c,) = vintage_cohorts(funds, as_of)
    assert c.median_tvpi == D("2.5")
