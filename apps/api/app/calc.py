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
from app.models import Document, Fact


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
    bases = {i.fact.basis for i in c.inputs}
    if len(bases) != 1:  # reported and adjusted figures never add together
        c.problems.append(f"inputs mix bases: {sorted(bases)}")
        return c
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


@dataclass
class Conflict:
    entity: str
    metric: str
    period: str
    basis: str
    values: list[tuple[Decimal, int]]  # (value, fact_id), ascending by value
    spread_pct: Decimal  # (max - min) / |max| * 100
    likely_rounding: bool
    severity: str = "material"  # rounding | minor (<5%) | material
    sources: list[dict] = field(default_factory=list)  # per fact: id, value, cited documents (file, page, quote)
    cross_document: bool = False  # the disagreeing facts cite different documents


ROUNDING_PCT = Decimal("0.5")


def find_conflicts(db: Session, tenant: str, scope: set[str] | None = None,
                   entity: str | None = None) -> list[Conflict]:
    """Same entity, metric, period and basis but different values across facts (rejected ones ignored).
    Reports; never picks a winner. Small spreads are flagged as probable rounding or scale noise."""
    q = db.query(Fact).filter(Fact.tenant_id == tenant, Fact.status != "rejected")
    if entity:
        q = q.filter(Fact.entity == entity)
    groups: dict[tuple[str, str, str, str, str], list[Fact]] = {}
    for f in q.all():
        if fact_visible(f, scope):
            groups.setdefault((f.entity, f.metric, f.period, f.basis, f.unit), []).append(f)
    out = []
    for (ent, metric, period, basis, _unit), fs in sorted(groups.items()):
        vals = sorted({(f.value, f.id) for f in fs})
        if len({v for v, _ in vals}) < 2:
            continue
        lo, hi = vals[0][0], vals[-1][0]
        spread = (hi - lo) / abs(hi) * 100 if hi else Decimal(0)
        rounding = spread <= ROUNDING_PCT
        names = {d.id: d.filename for d in db.query(Document).filter(
            Document.id.in_({s.document_id for f in fs for s in f.sources}))} if fs else {}
        srcs = [{"fact_id": f.id, "value": str(f.value), "documents": [
            {"document_id": s.document_id, "filename": names.get(s.document_id), "page": s.page, "locator": s.locator, "quote": s.quote}
            for s in f.sources]} for f in sorted(fs, key=lambda x: (x.value, x.id))]
        docs_per_value = {v: {s.document_id for f in fs if f.value == v for s in f.sources} for v, _ in vals}
        cross = len({frozenset(d) for d in docs_per_value.values()}) > 1
        out.append(Conflict(ent, metric, period, basis, vals, spread, rounding,
                            "rounding" if rounding else "minor" if spread < 5 else "material", srcs, cross))
    return out


# Debt-like items sit outside net debt but reduce the equity price. Each is optional: a document set that does not
# state one is reported as not found, which is not the same as zero.
DEBT_LIKE = (("pension", "pension_deficit"), ("deferred", "deferred_consideration"),
             ("earnout", "earn_out"), ("tax", "unpaid_tax"))


def debt_like(db: Session, tenant: str, entity: str, period: str,
              scope: set[str] | None = None) -> tuple[Calc, list[str]]:
    """Sum of the debt-like items stated for the period. Returns the calc and the metrics not found."""
    c = Calc("Debt-like items", entity, formula="sum of " + ", ".join(m for _, m in DEBT_LIKE) + " stated")
    not_found = []
    for role, metric in DEBT_LIKE:
        f = _find(db, tenant, entity, metric, period, scope)
        if f is None:
            not_found.append(metric)
        else:
            c.inputs.append(Input(role, 1, f))
    if not c.inputs:
        c.missing.append("no debt-like item stated for this period")
        return c, not_found
    units = {i.fact.unit for i in c.inputs}
    if len(units) != 1:
        c.problems.append(f"inputs use different units: {sorted(units)}")
        return c, not_found
    c.unit = units.pop()
    bases = {i.fact.basis for i in c.inputs}
    if len(bases) != 1:
        c.problems.append(f"inputs mix bases: {sorted(bases)}")
        return c, not_found
    c.value = sum((i.sign * i.fact.value for i in c.inputs), Decimal(0))
    return c, not_found


def net_debt_adjusted(db: Session, tenant: str, entity: str, period: str, scope: set[str] | None = None,
                      include_leases: bool = True) -> dict:
    """Net debt plus debt-like items: the figure an equity bridge deducts. The adjusted value is given only when net
    debt and at least one debt-like item are both stated, so a missing item is never silently counted as zero."""
    nd = net_debt(db, tenant, entity, period, scope, include_leases)
    dl, not_found = debt_like(db, tenant, entity, period, scope)
    adjusted = nd.value + dl.value if nd.ok and dl.ok and nd.unit == dl.unit else None
    return {"net_debt": nd, "debt_like": dl, "not_found": not_found, "adjusted": adjusted}


def to_usd(db: Session, tenant: str, c: Calc, rate_metric: str, period: str,
           scope: set[str] | None = None) -> Calc:
    """Restates a calc stated in another currency in USD, using a cited rate fact. The rate is a fact named
    `rate_metric` for `period` whose unit is USD and whose value is USD per one unit of the calc's currency. No
    rate on file means the calc stays missing a rate; the figure is never converted at a guessed rate."""
    if not c.ok or c.unit in (None, "USD"):
        return c
    rate = _find(db, tenant, c.entity, rate_metric, period, scope)
    if rate is None:
        c.missing.append(f"fx rate: {rate_metric} for {period}")
        c.value = None  # a figure without a rate is no figure in USD
        return c
    if rate.unit != "USD":
        c.problems.append(f"fx rate {rate_metric} is in {rate.unit}, expected USD per unit")
        c.value = None
        return c
    c.inputs.append(Input("fx rate", 1, rate))
    c.value = (c.value * rate.value).quantize(Decimal("0.01"))
    c.formula += f" x {rate_metric} ({c.unit} to USD)"
    c.unit = "USD"
    return c
