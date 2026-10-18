"""Market share from cited facts: each competitor's figure over the market size, both from the document set.

The market size is a fact on its own entity (for example "US PE software market"). Each competitor is every other
entity that has a verified, visible fact for the same metric and period. Shares are derived, labelled as such, and
computed only from figures in the same unit. Shares that sum past 100% are reported as a problem: a double-counted
or out-of-scope competitor is more likely than a market that is smaller than its players.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.models import Fact


def _verified(db: Session, tenant: str, metric: str, period: str, scope: set[str] | None) -> list[Fact]:
    rows = (db.query(Fact).filter_by(tenant_id=tenant, metric=metric, period=period, status="verified")
            .order_by(Fact.id.desc()).all())
    return [f for f in rows if fact_visible(f, scope)]


def shares(db: Session, tenant: str, market: str, metric: str, period: str,
           scope: set[str] | None = None) -> dict:
    """Result: market figure (with its fact id), competitors (entity, value, share %, fact id), problems. The latest
    visible fact per entity wins. A missing market figure means no shares, never a guessed market size."""
    out: dict = {"market": market, "metric": metric, "period": period, "derived": True, "market_fact": None,
                 "competitors": [], "problems": []}
    latest: dict[str, Fact] = {}
    for f in _verified(db, tenant, metric, period, scope):
        latest.setdefault(f.entity, f)
    size = latest.pop(market, None)
    if size is None:
        out["problems"].append(f"no visible market size: {metric} for {market} in {period}")
        return out
    out["market_fact"] = {"fact_id": size.id, "value": str(size.value), "unit": size.unit}
    mixed = sorted({f.unit for f in latest.values() if f.unit != size.unit})
    if mixed:
        out["problems"].append(f"competitor figures in {mixed}, market in {size.unit}; no shares computed")
        return out
    if size.value <= 0:
        out["problems"].append("market size is not positive; no shares computed")
        return out
    total = Decimal(0)
    for entity, f in sorted(latest.items(), key=lambda kv: -kv[1].value):
        pct = (f.value / size.value * 100).quantize(Decimal("0.1"))
        total += pct
        out["competitors"].append({"entity": entity, "value": str(f.value), "share_pct": str(pct), "fact_id": f.id})
    if total > 100:
        out["problems"].append(f"competitor shares sum to {total}% of the market; check scope and units")
    return out
