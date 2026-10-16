"""Portfolio tracking: companies and KPI observations that must cite a source.

An observation links to a verified Fact (document, page, quote already checked),
so a portfolio number can never exist without provenance. Values are bi-temporal
enough for restatements: a newer observation for the same (metric, period)
supersedes the older one, which stays in history.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base
from app.models import Fact


class PortfolioCompany(Base):
    __tablename__ = "portfolio_company"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256))
    sector: Mapped[str | None] = mapped_column(String(128), default=None)
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), default=None)


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
        row = {"period": o.period, "value": str(o.value), "threshold": str(thr.value),
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


def record_observation(db: Session, tenant_id: str, company_id: int, fact_id: int) -> KpiObservation:
    company = db.get(PortfolioCompany, company_id)
    if company is None or company.tenant_id != tenant_id:
        raise ValueError("company not found")
    fact = db.get(Fact, fact_id)
    if fact is None or fact.tenant_id != tenant_id or fact.status != "verified" or not fact.sources:
        raise ValueError("observation requires a verified, cited fact")
    obs = KpiObservation(tenant_id=tenant_id, company_id=company_id, metric=fact.metric, period=fact.period,
                         value=fact.value, unit=fact.unit, fact_id=fact.id,
                         observed_at=datetime.now(UTC).isoformat())
    db.add(obs)
    db.flush()
    for old in db.scalars(select(KpiObservation).where(
            KpiObservation.company_id == company_id, KpiObservation.metric == obs.metric,
            KpiObservation.period == obs.period, KpiObservation.id != obs.id,
            KpiObservation.superseded_by.is_(None))):
        old.superseded_by = obs.id
    db.commit()
    return obs


def current_kpis(db: Session, tenant_id: str, company_id: int) -> list[KpiObservation]:
    return list(db.scalars(select(KpiObservation).where(
        KpiObservation.tenant_id == tenant_id, KpiObservation.company_id == company_id, KpiObservation.superseded_by.is_(None))
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
