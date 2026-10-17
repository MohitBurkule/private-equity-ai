"""Derived facts: a value computed from cited component facts, never typed in.

A formula names its component metrics and how they combine. Every component must be a verified fact the
caller can see, in one unit, for one entity and period. Each component keeps its own citation, so a derived
value opens the same sources a reader would check by hand. Nothing is stored: a derived value is recomputed
on each read, so it cannot drift from the facts it came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.models import Fact

# formula name -> component metrics, summed. EBITDA here is operating income plus depreciation and amortization.
SUMS = {"ebitda": ("operating_income", "depreciation_and_amortization")}


def net_debt_points(facts: dict[tuple[str, str], tuple[Decimal, str, int | tuple[int, ...]]]
                    ) -> dict[str, tuple[Decimal, str, tuple[int, ...]]]:
    """Net debt per period = long-term debt less cash, from cited facts in one unit. The note numbers of both
    components are kept, so the derived value cites the same sources a reader would check by hand. Only the
    noncurrent debt fact is used, so a period without it gets no net debt rather than an understated one."""
    out: dict[str, tuple[Decimal, str, tuple[int, ...]]] = {}
    for (metric, period), (dv, du, dn) in facts.items():
        cash = facts.get(("cash", period))
        if metric == "long_term_debt" and cash is not None and cash[1] == du:
            out[period] = (dv - cash[0], du, (*note_numbers(dn), *note_numbers(cash[2])))
    return out


def note_numbers(n: int | tuple[int, ...]) -> tuple[int, ...]:
    """A plain fact carries one note number; a derived fact carries the numbers of all its components."""
    return n if isinstance(n, tuple) else (n,)


@dataclass
class Component:
    fact_id: int
    metric: str
    value: Decimal
    sources: list[dict]  # document_id, page, quote, for every citation the component carries


@dataclass
class Derived:
    formula: str
    entity: str
    period: str
    unit: str
    value: Decimal
    components: list[Component]


def derive(db: Session, tenant: str, scope: set[str] | None, formula: str, entity: str, period: str) -> Derived:
    """Raises ValueError when a component is missing, not verified, not visible, or in a different unit."""
    if formula not in SUMS:
        raise ValueError(f"unknown formula: {formula}")
    parts: list[Component] = []
    units: set[str] = set()
    for metric in SUMS[formula]:
        f = (db.query(Fact)
             .filter(Fact.tenant_id == tenant, Fact.entity == entity, Fact.period == period,
                     Fact.metric == metric, Fact.status == "verified")
             .first())
        if f is None or not f.sources or not fact_visible(f, scope):
            raise ValueError(f"{metric} for {entity} {period} is not a verified, cited, visible fact")
        units.add(f.unit)
        parts.append(Component(f.id, metric, f.value, [
            {"document_id": s.document_id, "page": s.page, "quote": s.quote} for s in f.sources]))
    if len(units) != 1:
        raise ValueError(f"components of {formula} are in different units: {', '.join(sorted(units))}")
    return Derived(formula, entity, period, units.pop(), sum((c.value for c in parts), Decimal(0)), parts)
