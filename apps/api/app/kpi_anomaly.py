"""Month-over-month outliers in a company's KPI pack, judged against that company's own history.

A new actual observation is compared with the size of its usual month-over-month moves. The median and the
median absolute deviation of past moves set the normal range, with a floor so a metric that barely moves does not
flag every small change. Outliers beyond 3 robust standard deviations raise a warning in the inbox, cited to the
pack cell. Nothing is corrected: the figure stays as the pack reported it, and a person decides.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import pairwise
from statistics import median

from sqlalchemy.orm import Session

from app.models import Alert, Fact
from app.portfolio import KpiObservation, PortfolioCompany

MIN_HISTORY = 6  # prior months needed before a move can be judged
MIN_MOVES = 5  # month-over-month changes needed to set the normal range
FLOOR = 0.05  # a metric's normal move is never taken as tighter than 5%
THRESHOLD = 3.0  # robust standard deviations


def _history(db: Session, obs: KpiObservation) -> list[KpiObservation]:
    rows = db.query(KpiObservation).filter(
        KpiObservation.tenant_id == obs.tenant_id, KpiObservation.company_id == obs.company_id,
        KpiObservation.metric == obs.metric, KpiObservation.kind == "actual",
        KpiObservation.superseded_by.is_(None), KpiObservation.id != obs.id,
        KpiObservation.period < obs.period).all()
    return sorted(rows, key=lambda o: o.period)


def judge_move(prior: list[float], new: float) -> tuple[float, float, float] | None:
    """(change, normal_move, z) for a new value after a prior series, or None when history is too thin to judge."""
    if len(prior) < MIN_HISTORY or prior[-1] == 0:
        return None
    moves = [(b - a) / abs(a) for a, b in pairwise(prior) if a != 0]
    if len(moves) < MIN_MOVES:
        return None
    centre = median(moves)
    spread = 1.4826 * median(abs(m - centre) for m in moves)
    change = (new - prior[-1]) / abs(prior[-1])
    return change, centre, (change - centre) / max(spread, FLOOR)


def flag_anomaly(db: Session, obs: KpiObservation) -> Alert | None:
    """Raises an inbox alert when this actual observation is an outlier for its company. Budgets and marks are not
    judged against actuals. Returns the alert, or None when there is none."""
    if obs.kind != "actual":
        return None
    prior = [float(o.value) for o in _history(db, obs)]
    verdict = judge_move(prior, float(obs.value))
    if verdict is None:
        return None
    change, centre, z = verdict
    if abs(z) < THRESHOLD:
        return None
    company = db.get(PortfolioCompany, obs.company_id)
    fact = db.get(Fact, obs.fact_id)
    cite = fact.sources[0].quote if fact and fact.sources else ""
    alert = Alert(tenant_id=obs.tenant_id, kind="kpi_anomaly", severity="warning",
                  title=f"{company.name}: {obs.metric} {obs.period} moved {change:+.0%} from last month",
                  detail=(f"Usual month-on-month move is about {centre:+.0%}. Cited pack cell: {cite}. "
                          "The figure is kept as reported; check it with the company."),
                  dedupe_key=f"kpi_anomaly:{obs.id}", fact_ids=json.dumps([obs.fact_id]),
                  created_at=datetime.now(UTC).isoformat())
    db.add(alert)
    db.commit()
    return alert
