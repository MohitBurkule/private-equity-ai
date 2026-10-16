from datetime import date
from decimal import Decimal as D

import pytest

from app.fundmetrics import vintage_cohorts

AS = date(2024, 12, 31)


def f(name, v, paid, dist, nav):
    return (name, v, [(date(v, 6, 1), -D(paid)), (date(2022, 6, 1), D(dist))], D(nav))


def test_pooled_and_median():
    c = vintage_cohorts([f("a", 2018, 100, 100, 100), f("b", 2018, 100, 0, 50), f("c", 2020, 50, 10, 0)], AS)
    assert [x.vintage for x in c] == [2018, 2020]
    assert c[0].funds == 2 and c[0].pooled_tvpi == D("1.25") and c[0].median_tvpi == D("1.25")
    assert c[1].pooled_tvpi == D("0.2")


def test_no_paid_in_gives_no_median():
    c = vintage_cohorts([("x", 2019, [], D(0)), f("b", 2019, 100, 0, 50)], AS)
    assert c[0].median_tvpi is None and c[0].pooled_tvpi == D("0.5")


def test_bad_flow_date_raises():
    with pytest.raises(ValueError):
        vintage_cohorts([("x", 2019, [(date(2030, 1, 1), -D(1))], D(0))], AS)
