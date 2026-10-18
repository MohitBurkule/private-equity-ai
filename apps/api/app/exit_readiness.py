"""Exit readiness for one portfolio company: a short set of checks drawn from data the firm already holds.

Each check states what it looked at and cites the facts behind it. A check with no data is `not_set`, never `pass`.
Nothing here recommends a sale: the list shows what a buyer's diligence would find in the firm's own records.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.models import Fact
from app.portfolio import Covenant, current_kpis, evaluate_covenant

MIN_MONTHS = 12


def _check(name: str, status: str, reason: str, fact_ids: list[int]) -> dict:
    return {"check": name, "status": status, "reason": reason, "fact_ids": fact_ids}


def readiness(db: Session, tenant: str, company_id: int, scope: set[str] | None) -> list[dict]:
    kpis = [o for o in current_kpis(db, tenant, company_id)
            if fact_visible(db.get(Fact, o.fact_id), scope)]
    periods = sorted({o.period for o in kpis})
    fact_ids = sorted({o.fact_id for o in kpis})
    out = [_check("kpi_history", "pass" if len(periods) >= MIN_MONTHS else "fail",
                  f"{len(periods)} months of current KPI actuals; {MIN_MONTHS} needed", fact_ids)]

    latest = periods[-1] if periods else None
    ebitda_latest = [o for o in kpis if o.metric == "ebitda" and o.period == latest]
    out.append(_check("ebitda_current", "pass" if ebitda_latest else ("fail" if latest else "not_set"),
                      f"EBITDA present for latest period {latest}" if ebitda_latest
                      else (f"no EBITDA for latest period {latest}" if latest else "no KPI actuals"),
                      [o.fact_id for o in ebitda_latest]))

    covs = db.query(Covenant).filter_by(tenant_id=tenant, company_id=company_id).all()
    if not covs:
        out.append(_check("covenants_clear", "not_set", "no covenants set for this company", []))
    else:
        tests = [t for c in covs for t in evaluate_covenant(db, c, scope)]
        breached = [t for t in tests if t["status"] in ("breach", "unit_mismatch")]
        out.append(_check("covenants_clear", "fail" if breached else "pass",
                          f"{len(breached)} covenant test(s) breached or unit-mismatched of {len(tests)}",
                          sorted({t[k] for t in tests for k in ("observation_fact_id", "threshold_fact_id") if t.get(k)})))
    return out
