"""Capital calls and NAV read from a fund-admin workbook or a capital-call notice (templates in app/fundadmin.py)
as cited facts. Shared by the manual endpoint and by sync, so a fund-admin file that arrives through a connector
gets its facts without a second call. Each fact goes through the citation gate; re-running stores nothing twice."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app import accounting as accounting_mod
from app import captable as captable_mod
from app import fundadmin as fundadmin_mod
from app.facts import CitationError, add_verified_fact
from app.models import Fact, PageRow
from app.portfolio import KpiObservation, PortfolioCompany, record_observation

# Monthly figures from a ledger that the covenant watcher tests against a company's covenants.
MONTHLY_METRICS = frozenset({"revenue_usd", "net_income_usd"})


def extract_facts(db: Session, tenant_id: str, doc, entity: str) -> tuple[list[int], list[dict]]:
    pages = db.query(PageRow).filter_by(document_id=doc.id).order_by(PageRow.number).all()
    text_pages = [(p.number, p.text) for p in pages]
    created, skipped, monthly = [], [], []
    found = (fundadmin_mod.extract(text_pages) + fundadmin_mod.extract_notice(text_pages)
             + accounting_mod.extract(text_pages) + captable_mod.extract(text_pages))
    for f in found:
        who_is = f.entity or entity
        same = [x for x in db.query(Fact).filter_by(tenant_id=tenant_id, entity=who_is, metric=f.metric,
                                                     period=f.period, status="verified")
                if any(s.document_id == doc.id and s.page == f.page and s.quote == f.quote for s in x.sources)]
        if same:  # the same cell again: keep the fact already stored
            created.append(same[0].id)
            continue
        try:
            fact = add_verified_fact(db, tenant_id=tenant_id, entity=who_is, metric=f.metric, period=f.period,
                                     value=Decimal(f.value), unit="USD", document_id=doc.id, page=f.page,
                                     quote=f.quote)
        except CitationError as e:
            skipped.append({"metric": f.metric, "period": f.period, "reason": str(e)})
            continue
        created.append(fact.id)
        if f.metric in MONTHLY_METRICS and f.entity is None:
            monthly.append(fact.id)
    _observe_monthly(db, tenant_id, entity, monthly)
    return created, skipped


def _observe_monthly(db: Session, tenant_id: str, entity: str, fact_ids: list[int]) -> None:
    """Monthly ledger figures become the company's KPI observations, so covenants on them are tested by the
    covenant watcher. Only when a portfolio company of that name exists; a fact is observed once."""
    company = db.query(PortfolioCompany).filter_by(tenant_id=tenant_id, name=entity).first()
    if company is None:
        return
    for fid in fact_ids:
        seen = db.query(KpiObservation).filter_by(tenant_id=tenant_id, company_id=company.id, fact_id=fid,
                                                  superseded_by=None).first()
        if seen is None:
            record_observation(db, tenant_id, company.id, fid)
