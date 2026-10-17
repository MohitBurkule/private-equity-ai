"""NTM is a derived estimate: month-weighted cited forecasts. Either forecast missing means no figure."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import calc


def _fact(value, unit="USD"):
    return SimpleNamespace(value=Decimal(value), unit=unit, basis="GAAP")


def _patch(monkeypatch, facts):
    monkeypatch.setattr(calc, "_find", lambda db, t, e, metric, period, scope: facts.get(period))


def test_weights_by_months_left_and_elapsed(monkeypatch):
    _patch(monkeypatch, {"FY24": _fact("1200"), "FY25": _fact("1500")})
    c = calc.ntm(None, "t", "A", "ebitda", "FY24", "FY25", months_elapsed=3)
    # 9/12 of 1200 plus 3/12 of 1500
    assert c.value == Decimal("1275.00")
    assert c.unit == "USD"
    assert c.name.endswith("(derived)")
    assert "0.7500" in c.formula and "0.2500" in c.formula


@pytest.mark.parametrize("period", ["FY24", "FY25"])
def test_missing_forecast_means_no_figure(monkeypatch, period):
    facts = {"FY24": _fact("1200"), "FY25": _fact("1500")}
    del facts[period]
    _patch(monkeypatch, facts)
    c = calc.ntm(None, "t", "A", "ebitda", "FY24", "FY25", months_elapsed=6)
    assert c.value is None
    assert c.missing == [f"{'current FY' if period == 'FY24' else 'next FY'} forecast: ebitda for {period}"]


def test_mixed_units_are_a_problem(monkeypatch):
    _patch(monkeypatch, {"FY24": _fact("1200"), "FY25": _fact("1100", unit="EUR")})
    c = calc.ntm(None, "t", "A", "ebitda", "FY24", "FY25", months_elapsed=0)
    assert c.value is None
    assert c.problems


def test_months_out_of_range_rejected():
    with pytest.raises(ValueError):
        calc.ntm(None, "t", "A", "ebitda", "FY24", "FY25", months_elapsed=13)
