from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.fundmetrics import fund_metrics, xirr
from app.main import app
from tests.helpers import new_tenant


def test_known_xirr_one_year_doubling():
    r, note = xirr([(date(2020, 1, 1), -100.0), (date(2021, 1, 1), 110.0)])
    assert note == "" and r == pytest.approx(0.10, abs=0.002)  # 366 days in 2020 leaves a hair under 10%


def test_multiples_with_nav():
    m = fund_metrics([(date(2020, 1, 1), D(-100)), (date(2021, 1, 1), D(-50)), (date(2023, 1, 1), D(60))],
                     D(120), date(2024, 1, 1))
    assert (m.paid_in, m.distributed) == (150, 60)
    assert m.dpi == D("0.4") and m.rvpi == D("0.8") and m.tvpi == D("1.2")
    assert m.irr is not None and 0.03 < m.irr < 0.08


def test_no_irr_without_a_positive_flow_and_no_division_by_zero():
    m = fund_metrics([(date(2020, 1, 1), D(-100))], D(0), date(2024, 1, 1))
    assert m.irr is None and m.irr_note and m.dpi == 0
    m = fund_metrics([], D(10), date(2024, 1, 1))
    assert m.tvpi is None and m.irr is None


def test_total_loss_gives_minus_one_ish_or_a_reason_never_a_crash():
    m = fund_metrics([(date(2020, 1, 1), D(-100)), (date(2022, 1, 1), D(1))], D(0), date(2022, 1, 1))
    assert m.irr is not None and m.irr < -0.8


def test_bad_inputs():
    with pytest.raises(ValueError):
        fund_metrics([(date(2025, 1, 1), D(1))], D(0), date(2024, 1, 1))
    with pytest.raises(ValueError):
        fund_metrics([], D(-1), date(2024, 1, 1))


def test_endpoint():
    c = TestClient(app)
    h = new_tenant(c, "fm1")
    r = c.post("/calc/fund-metrics", headers=h, json={"as_of": "2024-01-01", "nav": "120", "flows": [
        {"date": "2020-01-01", "amount": "-100"}, {"date": "2021-01-01", "amount": "-50"}, {"date": "2023-01-01", "amount": "60"}]})
    j = r.json()
    assert r.status_code == 200 and D(j["tvpi"]) == D("1.2") and D(j["dpi"]) == D("0.4") and j["irr"] is not None
    assert c.post("/calc/fund-metrics", headers=h, json={"as_of": "2024-13-01", "nav": "1", "flows": []}).status_code == 422
    assert c.post("/calc/fund-metrics", headers=h, json={"as_of": "2024-01-01", "nav": "1",
                  "flows": [{"date": "2025-01-01", "amount": "1"}]}).status_code == 422
