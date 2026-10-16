"""Deal arithmetic done in code from cited, verified facts: LTM, net debt, net working capital.

A result is returned only if every input fact exists (status verified, visible to the caller).
Missing inputs are listed, never guessed or defaulted to zero. Each result carries its formula
and the input facts (with sources) so a reviewer can trace every number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.models import Fact


@dataclass
class Input:
    role: str  # name in the formula
    sign: int  # +1 or -1
    fact: Fact


@dataclass
class Calc:
    name: str
    entity: str
    unit: str | None = None
    value: Decimal | None = None
    formula: str = ""
    inputs: list[Input] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # e.g. unit mismatch

    @property
    def ok(self) -> bool:
        return self.value is not None


def _find(db: Session, tenant: str, entity: str, metric: str, period: str,
          scope: set[str] | None) -> Fact | None:
    rows = (db.query(Fact).filter_by(tenant_id=tenant, entity=entity, metric=metric, period=period,
                                     status="verified").order_by(Fact.id.desc()).all())
    return next((f for f in rows if fact_visible(f, scope)), None)  # latest visible wins


def _combine(c: Calc, wanted: list[tuple[str, str, str, int]], db: Session, tenant: str,
             scope: set[str] | None) -> Calc:
    """wanted: (role, metric, period, sign). Fills c.inputs / c.missing and the value when complete."""
    for role, metric, period, sign in wanted:
        f = _find(db, tenant, c.entity, metric, period, scope)
        if f is None:
            c.missing.append(f"{role}: {metric} for {period}")
        else:
            c.inputs.append(Input(role, sign, f))
    if c.missing:
        return c
    units = {i.fact.unit for i in c.inputs}
    if len(units) != 1:
        c.problems.append(f"inputs use different units: {sorted(units)}")
        return c
    c.unit = units.pop()
    c.value = sum((i.sign * i.fact.value for i in c.inputs), Decimal(0))
    return c


def ltm(db: Session, tenant: str, entity: str, metric: str, fy: str, ytd: str, ytd_prior: str,
        scope: set[str] | None = None) -> Calc:
    """LTM = last fiscal year + current YTD - prior-year YTD (same metric, same basis of period)."""
    c = Calc(f"LTM {metric}", entity, formula=f"{fy} + {ytd} - {ytd_prior}")
    return _combine(c, [("fiscal year", metric, fy, 1), ("current YTD", metric, ytd, 1),
                        ("prior YTD", metric, ytd_prior, -1)], db, tenant, scope)


def net_debt(db: Session, tenant: str, entity: str, period: str, scope: set[str] | None = None,
             include_leases: bool = True) -> Calc:
    """Net debt = total_debt (+ lease_liabilities) - cash. Leases are a deal choice, so it is a flag."""
    parts = [("debt", "total_debt", period, 1)]
    if include_leases:
        parts.append(("leases", "lease_liabilities", period, 1))
    parts.append(("cash", "cash", period, -1))
    c = Calc("Net debt", entity, formula="debt" + (" + leases" if include_leases else "") + " - cash")
    return _combine(c, parts, db, tenant, scope)


def nwc(db: Session, tenant: str, entity: str, period: str, scope: set[str] | None = None) -> Calc:
    """Trade NWC = (current assets - cash) - (current liabilities - short-term debt)."""
    c = Calc("Net working capital", entity,
             formula="(current assets - cash) - (current liabilities - short-term debt)")
    return _combine(c, [("current assets", "current_assets", period, 1), ("cash", "cash", period, -1),
                        ("current liabilities", "current_liabilities", period, -1),
                        ("short-term debt", "short_term_debt", period, 1)], db, tenant, scope)
