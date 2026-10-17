"""A figure in another currency is restated in USD only with a cited rate fact. No rate, no conversion."""
from decimal import Decimal
from types import SimpleNamespace

from app import calc


def _fact(value, unit="USD", basis="GAAP"):
    return SimpleNamespace(value=Decimal(value), unit=unit, basis=basis)


def _eur_calc(value="100"):
    c = calc.Calc("Net debt", "A", unit="EUR", value=Decimal(value))
    return c


def _patch(monkeypatch, facts):
    monkeypatch.setattr(calc, "_find", lambda db, t, e, metric, period, scope: facts.get(metric))


def test_converts_with_cited_usd_per_unit_rate(monkeypatch):
    _patch(monkeypatch, {"fx_usd_per_eur": _fact("1.0850")})
    c = calc.to_usd(None, "t", _eur_calc(), "fx_usd_per_eur", "FY23", None)
    assert c.unit == "USD"
    assert c.value == Decimal("108.50")
    assert c.inputs[-1].fact.value == Decimal("1.0850")
    assert c.problems == [] and c.missing == []


def test_missing_rate_leaves_calc_unconverted(monkeypatch):
    _patch(monkeypatch, {})
    c = calc.to_usd(None, "t", _eur_calc(), "fx_usd_per_eur", "FY23", None)
    assert c.unit == "EUR"
    assert c.value is None and not c.ok
    assert c.missing == ["fx rate: fx_usd_per_eur for FY23"]


def test_rate_in_wrong_unit_is_a_problem(monkeypatch):
    _patch(monkeypatch, {"fx_usd_per_eur": _fact("0.92", unit="EUR")})
    c = calc.to_usd(None, "t", _eur_calc(), "fx_usd_per_eur", "FY23", None)
    assert c.unit == "EUR"
    assert c.value is None
    assert c.problems == ["fx rate fx_usd_per_eur is in EUR, expected USD per unit"]


def test_usd_calc_is_untouched(monkeypatch):
    _patch(monkeypatch, {})
    c = calc.Calc("Net debt", "A", unit="USD", value=Decimal(50))
    assert calc.to_usd(None, "t", c, "fx_usd_per_eur", "FY23", None) is c
    assert c.value == Decimal(50)
