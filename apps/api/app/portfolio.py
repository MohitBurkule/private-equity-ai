"""Portfolio tracking: companies and KPI observations that must cite a source.

An observation links to a verified Fact (document, page, quote already checked),
so a portfolio number can never exist without provenance. Values are bi-temporal
enough for restatements: a newer observation for the same (metric, period)
supersedes the older one, which stays in history.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base
from app.models import Fact


class PortfolioCompany(Base):
    __tablename__ = "portfolio_company"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256))
    sector: Mapped[str | None] = mapped_column(String(128), default=None)
    sic: Mapped[str | None] = mapped_column(String(8), default=None)  # SIC code; add-on search matches on it too
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), default=None)
    label_map: Mapped[str | None] = mapped_column(Text, default=None)  # JSON {workbook label: KPI}, merged over the default map


class KpiObservation(Base):
    __tablename__ = "kpi_observation"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("portfolio_company.id"), nullable=False)
    metric: Mapped[str] = mapped_column(String(128))
    period: Mapped[str] = mapped_column(String(64))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    unit: Mapped[str] = mapped_column(String(32))
    fact_id: Mapped[int] = mapped_column(ForeignKey("fact.id"), nullable=False)  # citation
    observed_at: Mapped[str] = mapped_column(String(40))
    superseded_by: Mapped[int | None] = mapped_column(Integer, default=None)
    # "actual", "budget" or "mark". A budget or mark figure is cited like an actual but never supersedes one, so
    # they can stand for the same metric and period and be compared.
    kind: Mapped[str] = mapped_column(String(16), default="actual", server_default="actual")


class Covenant(Base):
    """A covenant test on a KPI. The threshold is a verified, cited fact, never a typed-in number."""
    __tablename__ = "covenant"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("portfolio_company.id"), nullable=False)
    kpi_metric: Mapped[str] = mapped_column(String(128))
    operator: Mapped[str] = mapped_column(String(2))  # "<=" (must not exceed) or ">=" (must not fall below)
    threshold_fact_id: Mapped[int] = mapped_column(ForeignKey("fact.id"), nullable=False)


def add_covenant(db: Session, tenant_id: str, company_id: int, kpi_metric: str, operator: str,
                 threshold_fact_id: int) -> Covenant:
    if operator not in ("<=", ">="):
        raise ValueError("operator must be <= or >=")
    company = db.get(PortfolioCompany, company_id)
    if company is None or company.tenant_id != tenant_id:
        raise ValueError("company not found")
    fact = db.get(Fact, threshold_fact_id)
    if fact is None or fact.tenant_id != tenant_id or fact.status != "verified" or not fact.sources:
        raise ValueError("covenant threshold must be a verified, cited fact")
    cov = Covenant(tenant_id=tenant_id, company_id=company_id, kpi_metric=kpi_metric, operator=operator,
                   threshold_fact_id=threshold_fact_id)
    db.add(cov)
    db.commit()
    return cov


def evaluate_covenant(db: Session, cov: Covenant, scope: set[str] | None = None) -> list[dict]:
    """One result per current observation of the KPI: ok / breach, with headroom in percent of the
    threshold (positive = room left). Units must match or the row says so instead of comparing."""
    from app.acl import fact_visible
    thr = db.get(Fact, cov.threshold_fact_id)
    if thr is None or not fact_visible(thr, scope):
        return []
    out = []
    for o in current_kpis(db, cov.tenant_id, cov.company_id):
        if o.metric != cov.kpi_metric:
            continue
        obs_fact = db.get(Fact, o.fact_id)
        if obs_fact is None or not fact_visible(obs_fact, scope):
            continue
        row = {"period": o.period, "value": str(o.value), "threshold": str(thr.value), "unit": o.unit,
               "observation_fact_id": o.fact_id, "threshold_fact_id": thr.id}
        if o.unit != thr.unit:
            row["status"] = "unit_mismatch"
        else:
            ok = o.value <= thr.value if cov.operator == "<=" else o.value >= thr.value
            row["status"] = "ok" if ok else "breach"
            if thr.value:
                gap = (thr.value - o.value) if cov.operator == "<=" else (o.value - thr.value)
                row["headroom_pct"] = str((gap / abs(thr.value) * 100).quantize(Decimal("0.1")))
        out.append(row)
    return out


def record_observation(db: Session, tenant_id: str, company_id: int, fact_id: int,
                       kind: str = "actual") -> KpiObservation:
    company = db.get(PortfolioCompany, company_id)
    if company is None or company.tenant_id != tenant_id:
        raise ValueError("company not found")
    fact = db.get(Fact, fact_id)
    if fact is None or fact.tenant_id != tenant_id or fact.status != "verified" or not fact.sources:
        raise ValueError("observation requires a verified, cited fact")
    obs = KpiObservation(tenant_id=tenant_id, company_id=company_id, metric=fact.metric, period=fact.period,
                         value=fact.value, unit=fact.unit, fact_id=fact.id,
                         observed_at=datetime.now(UTC).isoformat(), kind=kind)
    db.add(obs)
    db.flush()
    for old in db.scalars(select(KpiObservation).where(
            KpiObservation.company_id == company_id, KpiObservation.metric == obs.metric,
            KpiObservation.period == obs.period, KpiObservation.kind == kind, KpiObservation.id != obs.id,
            KpiObservation.superseded_by.is_(None))):
        old.superseded_by = obs.id
    db.commit()
    return obs


def current_kpis(db: Session, tenant_id: str, company_id: int, kind: str = "actual") -> list[KpiObservation]:
    return list(db.scalars(select(KpiObservation).where(
        KpiObservation.tenant_id == tenant_id, KpiObservation.company_id == company_id, KpiObservation.kind == kind,
        KpiObservation.superseded_by.is_(None))
        .order_by(KpiObservation.metric, KpiObservation.period)))


def qoq_change(db: Session, tenant_id: str, company_id: int, metric: str, p_new: str,
               p_old: str) -> Decimal | None:
    """Percent change computed in code from current observations; None if either missing/zero."""
    cur = {o.period: o for o in current_kpis(db, tenant_id, company_id) if o.metric == metric}
    if p_new not in cur or p_old not in cur or cur[p_old].value == 0:
        return None
    if cur[p_new].unit != cur[p_old].unit:
        return None
    return (cur[p_new].value - cur[p_old].value) / abs(cur[p_old].value) * 100


def budget_variance(actual: Decimal, budget: Decimal) -> tuple[Decimal, Decimal | None]:
    """Actual minus budget, and that gap as a share of the budget. The share is None when the budget is zero, since
    there is no base to measure against."""
    diff = actual - budget
    return diff, (diff / abs(budget) * 100 if budget != 0 else None)


MARK_METRIC = "equity_value"  # the holding's value, cited, at each period end


def roll_forward(opening: Decimal | None, closing: Decimal | None, contributions: Decimal | None,
                 distributions: Decimal | None) -> Decimal | None:
    """Change in value over the period: closing mark, less opening mark, less the cash put in, plus the cash taken
    out. None unless all four are present, so a gap never reads as a gain or a loss."""
    if None in (opening, closing, contributions, distributions):
        return None
    return closing - opening - contributions + distributions


def _month_index(period: str) -> int | None:
    """Month number of a YYYY-MM period, None for any other period label (quarters, years, custom)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", period)
    return int(m[1]) * 12 + int(m[2]) - 1 if m and 1 <= int(m[2]) <= 12 else None


def compliance_summary(tests: list[dict]) -> dict:
    """Summary of one covenant's tests over its monthly ledger periods (rows from evaluate_covenant). `missing` lists
    the months between the first and last tested period that have no test, so a gap in the ledger feed shows up
    instead of reading as compliance. Status is breach if any tested month breached, no_data if none was tested."""
    rows = sorted(tests, key=lambda t: t["period"])
    breaches = [t["period"] for t in rows if t["status"] == "breach"]
    seen = {t["period"] for t in rows}
    missing = []
    idx = [_month_index(t["period"]) for t in rows]
    if rows and None not in (idx[0], idx[-1]):
        for i in range(idx[0], idx[-1] + 1):
            key = f"{i // 12:04d}-{i % 12 + 1:02d}"
            if key not in seen:
                missing.append(key)
    headrooms = [(Decimal(t["headroom_pct"]), t["period"]) for t in rows if "headroom_pct" in t]
    low = min(headrooms) if headrooms else None
    status = "no_data" if not rows else ("breach" if breaches else "ok")
    return {"status": status, "tested_months": len(rows), "first_breach": breaches[0] if breaches else None,
            "latest": rows[-1] if rows else None,
            "min_headroom": {"period": low[1], "headroom_pct": str(low[0])} if low else None,
            "missing": missing}
