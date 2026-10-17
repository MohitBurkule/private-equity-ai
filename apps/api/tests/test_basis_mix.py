"""Reported and adjusted figures never add together: a mixed-basis calc is a problem, not a number."""
from decimal import Decimal
from types import SimpleNamespace

from app import calc


def _fact(value, basis):
    return SimpleNamespace(value=Decimal(value), unit="USD", basis=basis)


def test_mixed_basis_inputs_are_a_problem_not_a_value(monkeypatch):
    facts = {"total debt": _fact("500", "GAAP"), "cash": _fact("120", "extracted")}
    monkeypatch.setattr(calc, "_find", lambda db, t, e, metric, period, scope: facts.get(metric))
    c = calc._combine(calc.Calc("Net debt", "A"), [("debt", "total debt", "FY23", 1), ("cash", "cash", "FY23", -1)],
                      None, "t", None)
    assert c.value is None
    assert c.problems == ["inputs mix bases: ['GAAP', 'extracted']"]


def test_same_basis_still_computes(monkeypatch):
    facts = {"total debt": _fact("500", "GAAP"), "cash": _fact("120", "GAAP")}
    monkeypatch.setattr(calc, "_find", lambda db, t, e, metric, period, scope: facts.get(metric))
    c = calc._combine(calc.Calc("Net debt", "A"), [("debt", "total debt", "FY23", 1), ("cash", "cash", "FY23", -1)],
                      None, "t", None)
    assert c.value == Decimal(380)
    assert c.problems == []
