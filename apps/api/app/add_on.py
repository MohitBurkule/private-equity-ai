"""Add-on search: targets in a portfolio company's sector, minus companies already owned.

Pure code over stored targets and the firm's accepted screening rule. A target whose sector is unknown
is not listed, since the sector is not guessed. Owned names are excluded with the same matcher as the
seen-before lookup, so "Acme Ltd" and "Acme Holdings" count as one company.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import firm_knowledge as fk
from app import targets as tg
from app.alerts import screening_criteria
from app.models import Target
from app.portfolio import PortfolioCompany
from app.seen_before import _match, normalise


def add_on_candidates(db: Session, tenant_id: str, company_id: int, limit: int = 50) -> dict:
    co = db.query(PortfolioCompany).filter_by(tenant_id=tenant_id, id=company_id).one_or_none()
    if co is None:
        raise LookupError("no such portfolio company")
    if not co.sector:
        return {"company": co.name, "sector": None, "items": [], "excluded_owned": 0,
                "note": "portfolio company has no sector, so no add-on search is run"}
    owned = [normalise(c.name) for c in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id)]
    rule = fk.newest_accepted(db, tenant_id, "deal_screening_criteria")
    min_rev = screening_criteria(rule.value).min_revenue if rule else None
    criteria = tg.Criteria(sectors=[co.sector], min_revenue=min_rev)
    items, excluded = [], 0
    for t in db.query(Target).filter_by(tenant_id=tenant_id).filter(Target.status != "passed").order_by(Target.id):
        if any(_match(o, t.name) for o in owned if o):
            excluded += 1
            continue
        res = tg.evaluate(t, criteria)
        if res["verdict"] == "fail" or res["criteria"].get("sector") != "pass":
            continue
        items.append({**tg.to_dict(t), "verdict": res["verdict"], "criteria": res["criteria"]})
    items.sort(key=lambda i: (i["verdict"] != "match", i["id"]))
    return {"company": co.name, "sector": co.sector, "items": items[:limit], "total": len(items),
            "excluded_owned": excluded,
            "rule": None if rule is None else {"document_id": rule.document_id, "page": rule.page, "quote": rule.quote}}
