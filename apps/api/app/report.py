"""Portfolio reporting pack: current KPIs with their sources, covenant tests, breaches first.

Only facts visible to the caller are used. Nothing is estimated; a company with no
visible observations says so.
"""
from __future__ import annotations

import io

from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.models import Fact
from app.portfolio import Covenant, PortfolioCompany, current_kpis, evaluate_covenant


def _src(f: Fact) -> list[dict]:
    return [{"document_id": s.document_id, "page": s.page, "quote": s.quote} for s in f.sources]


def build_report(db: Session, tenant_id: str, scope: set[str] | None = None) -> dict:
    companies = []
    breaches = []
    for co in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id).order_by(PortfolioCompany.id):
        kpis = []
        for o in current_kpis(db, tenant_id, co.id):
            f = db.get(Fact, o.fact_id)
            if f is None or not fact_visible(f, scope):
                continue
            kpis.append({"metric": o.metric, "period": o.period, "value": str(o.value), "unit": o.unit,
                         "fact_id": o.fact_id, "sources": _src(f)})
        covs = []
        for c in db.query(Covenant).filter_by(tenant_id=tenant_id, company_id=co.id):
            tests = evaluate_covenant(db, c, scope)
            thr = db.get(Fact, c.threshold_fact_id)
            covs.append({"id": c.id, "kpi_metric": c.kpi_metric, "operator": c.operator, "tests": tests,
                         "threshold_sources": _src(thr) if thr is not None and fact_visible(thr, scope) else []})
            breaches += [{"company": co.name, "kpi_metric": c.kpi_metric, **t}
                         for t in tests if t["status"] in ("breach", "unit_mismatch")]
        companies.append({"id": co.id, "name": co.name, "sector": co.sector,
                          "ownership_pct": None if co.ownership_pct is None else str(co.ownership_pct),
                          "kpis": kpis, "covenants": covs})
    return {"companies": companies, "breaches": breaches}


def _cite(sources: list[dict]) -> str:
    return "; ".join(f"doc {s['document_id'][:8]} p.{s['page']}" for s in sources) or "no source visible"


def build_report_docx(db: Session, tenant_id: str, scope: set[str] | None = None) -> bytes:
    from docx import Document as Docx
    r = build_report(db, tenant_id, scope)
    d = Docx()
    d.add_heading("Portfolio report", level=1)
    d.add_paragraph("DRAFT. Every figure is a verified fact with a cited source page.")
    d.add_heading("Covenant alerts", level=2)
    if not r["breaches"]:
        d.add_paragraph("No breaches or unit mismatches in the visible data.")
    for b in r["breaches"]:
        d.add_paragraph(f"{b['company']}: {b['kpi_metric']} {b['period']} {b['status'].upper()} "
                        f"(value {b['value']}, threshold {b['threshold']})", style="List Bullet")
    for co in r["companies"]:
        d.add_heading(co["name"], level=2)
        if not co["kpis"]:
            d.add_paragraph("No visible KPI observations.")
        for k in co["kpis"]:
            d.add_paragraph(f"{k['metric']} {k['period']}: {k['value']} {k['unit']} ({_cite(k['sources'])})",
                            style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
