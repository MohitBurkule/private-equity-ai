"""Quality of earnings, deterministic part: normalized EBITDA from a company's reviewed bridge lines.

Normalized EBITDA = reported EBITDA + add-backs - deductions, all taken from bridge lines a reviewer has accepted
(status verified). If any line for the period is still unreviewed, the result is withheld and the lines are named,
because a total that moves when a reviewer changes one line is not a number to put in a memo. Add-backs above
ONE_OFF_PCT of reported EBITDA are flagged as likely one-offs for a person to look at; they stay in the total.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.calc import Calc, Input, nwc
from app.models import Fact

ONE_OFF_PCT = Decimal(10)


def normalized_ebitda(db: Session, tenant: str, entity: str, period: str,
                      scope: set[str] | None = None) -> Calc:
    c = Calc("Normalized EBITDA", entity, formula="reported + add-backs - deductions", unit="USD")
    lines = [f for f in db.query(Fact).filter_by(tenant_id=tenant, entity=entity, period=period, unit="USD")
             .filter(Fact.metric.like("ebitda_bridge %")).order_by(Fact.id).all() if fact_visible(f, scope)]
    unreviewed = [f for f in lines if f.status not in ("verified", "rejected")]
    if unreviewed:
        c.missing.append(f"{len(unreviewed)} bridge line(s) not yet reviewed: ids {[f.id for f in unreviewed]}")
        return c
    verified = [f for f in lines if f.status == "verified"]
    kinds = {"reported": (1, 1), "add_back": (1, None), "deduction": (-1, None)}
    reported = [f for f in verified if f.metric == "ebitda_bridge reported"]
    if len(reported) != 1:
        c.missing.append(f"reported EBITDA: expected one reviewed line, found {len(reported)}")
        return c
    for f in verified:
        kind = f.metric.removeprefix("ebitda_bridge ")
        if kind not in kinds:
            continue  # adjusted totals are not summed: the bridge check compares them, nothing else reads them
        sign = kinds[kind][0]
        c.inputs.append(Input(kind, sign, f))
    if c.missing:
        return c
    c.value = sum((i.sign * i.fact.value for i in c.inputs), Decimal(0))
    return c


def one_off_flags(c: Calc) -> list[dict]:
    """Add-backs above ONE_OFF_PCT of reported EBITDA. Empty when the calc is not complete."""
    if not c.ok:
        return []
    reported = next((i.fact.value for i in c.inputs if i.role == "reported"), None)
    if not reported:
        return []
    limit = abs(reported) * ONE_OFF_PCT / 100
    return [{"fact_id": i.fact.id, "amount": str(i.fact.value), "quote": i.fact.sources[0].quote,
             "locator": i.fact.sources[0].locator} for i in c.inputs
            if i.role == "add_back" and i.fact.value > limit]


def nwc_peg(db: Session, tenant: str, entity: str, periods: list[str],
            scope: set[str] | None = None) -> Calc:
    """Peg = average trade NWC over the given periods. A single period's NWC swings with year-end timing, so the
    peg is a trailing average, not the closing balance. Every period must be complete: a peg built from a
    partial set would move silently when a missing period is later loaded."""
    c = Calc("NWC peg", entity, formula=f"average of trade NWC over {', '.join(periods)}", unit="USD")
    if not periods:
        c.missing.append("no periods given for the peg")
        return c
    values = []
    for p in periods:
        n = nwc(db, tenant, entity, p, scope)
        if not n.ok:
            c.missing.extend(f"{p} {m}" for m in n.missing or n.problems)
        elif n.unit != "USD":
            c.problems.append(f"{p} NWC is in {n.unit}, expected USD")
        else:
            values.append(n.value)
    if c.missing or c.problems:
        return c
    c.value = (sum(values, Decimal(0)) / len(values)).quantize(Decimal("0.01"))
    return c
