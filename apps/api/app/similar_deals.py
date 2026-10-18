"""Past IC decisions on deals like this one: same SIC division or same sponsor, each decision cited by its id.

Why it matters: the firm's own history of proceed, pass and dissent is the nearest thing to precedent a partner
has. A decision is shown only with its rationale and any dissent recorded on it, never as a recommendation.
Matching is on the firm's own deal fields. Deals carry no revenue, so no size band is applied here; the caller
sees which rule matched each deal and can judge the size gap.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Deal, ICDecision
from app.seen_before import normalise


def _division(sic: str | None) -> str | None:
    return sic[:2] if sic else None


def _matches(subject: Deal, other: Deal) -> list[str]:
    rules = []
    if subject.sic and other.sic and _division(subject.sic) == _division(other.sic):
        rules.append("same SIC division")
    if subject.sponsor and other.sponsor and normalise(subject.sponsor) == normalise(other.sponsor):
        rules.append("same sponsor")
    return rules


def similar_decisions(db: Session, tenant: str, deal_name: str, scope: set[str] | None) -> dict:
    subject = db.query(Deal).filter_by(tenant_id=tenant, name=deal_name).one_or_none()
    if subject is None:
        raise ValueError("deal not found")
    others = [d for d in db.query(Deal).filter(Deal.tenant_id == tenant, Deal.name != deal_name).all()
              if scope is None or d.name in scope]
    matched = {d.name: rules for d in others if (rules := _matches(subject, d))}
    if not matched:
        return {"subject": deal_name, "matches": []}
    decisions = (db.query(ICDecision)
                 .filter(ICDecision.tenant_id == tenant, ICDecision.deal.in_(list(matched)))
                 .order_by(ICDecision.recorded_at.desc(), ICDecision.id.desc()).all())
    rows = [{"decision_id": d.id, "deal": d.deal, "outcome": d.outcome, "rationale": d.rationale,
             "dissent": d.dissent, "dissenter": d.dissenter, "recorded_at": d.recorded_at,
             "matched_on": matched[d.deal]} for d in decisions]
    # Recorded dissent first: a partner most needs to see where the room disagreed.
    rows.sort(key=lambda r: r["dissent"] is None)
    return {"subject": deal_name, "matches": rows}
