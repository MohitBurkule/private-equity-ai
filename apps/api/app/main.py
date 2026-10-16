import os
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.answer import answer_question
from app.audit import log_event, verify_chain
from app.auth import admin_token_ok, create_tenant, tenant_for_key
from app.db import Base, make_engine, make_session_factory
from app.edgar import fetch_companyfacts
from app.facts import CitationError, add_verified_fact
from app.ingest import ingest_upload
from app.llm import LLM, NoLLMConfigured, get_llm
from app.memo import build_memo
from app.models import Document, PageRow
from app.portfolio import (
    PortfolioCompany,
    current_kpis,
    qoq_change,
    record_observation,
)
from app.rls import apply_rls, bind_tenant, install_tenant_hook, verify_app_role
from app.search import PageIndex
from app.xbrl import candidates, crosscheck, load_companyfacts

engine = make_engine()
SessionLocal = make_session_factory(engine)
install_tenant_hook(SessionLocal)
# Schema + RLS run as the owner role (MIGRATE_DATABASE_URL); requests run as the app role.
_owner = make_engine(os.environ.get("MIGRATE_DATABASE_URL")) if os.environ.get("MIGRATE_DATABASE_URL") else engine
Base.metadata.create_all(_owner)
apply_rls(_owner, os.environ.get("APP_DB_ROLE"))
verify_app_role(engine)

app = FastAPI(title="PE Platform API", version="0.0.1")


def get_db():
    with SessionLocal() as s:
        yield s


Db = Annotated[Session, Depends(get_db)]


def get_tenant(db: Db, authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    tenant = tenant_for_key(db, authorization[7:].strip())
    if tenant is None:
        raise HTTPException(401, "invalid token")
    bind_tenant(db, tenant)
    return tenant


Tenant = Annotated[str, Depends(get_tenant)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class TenantIn(BaseModel):
    name: str


@app.post("/admin/tenants", status_code=201)
def admin_create_tenant(body: TenantIn, db: Db, x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    t, key = create_tenant(db, body.name)
    return {"tenant_id": t.id, "api_key": key, "note": "store this key now; it is not shown again"}


@app.post("/documents")
async def upload(file: Annotated[UploadFile, File()], db: Db, tenant: Tenant):
    data = await file.read()
    try:
        doc = ingest_upload(db, tenant, data, file.filename or "upload.pdf")
    except Exception as e:  # corrupt / encrypted / empty files are flagged, never skipped
        raise HTTPException(422, f"cannot parse file: {e}") from e
    log_event(db, tenant, "api", "document.upload", {"document_id": doc.id, "filename": doc.filename})
    return {"id": doc.id, "filename": doc.filename, "n_pages": doc.n_pages}


def _own_doc(db: Session, tenant: str, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.tenant_id != tenant:  # same 404 for "missing" and "someone else's"
        raise HTTPException(404, "document not found")
    return doc


@app.get("/documents/{doc_id}/pages/{number}")
def get_page(doc_id: str, number: int, db: Db, tenant: Tenant):
    _own_doc(db, tenant, doc_id)
    row = db.query(PageRow).filter_by(document_id=doc_id, number=number).one_or_none()
    if row is None:
        raise HTTPException(404, "page not found")
    return {"document_id": doc_id, "page": number, "text": row.text}


@app.get("/documents")
def list_documents(db: Db, tenant: Tenant):
    return [{"id": d.id, "filename": d.filename, "n_pages": d.n_pages}
            for d in db.query(Document).filter_by(tenant_id=tenant).all()]


class FactIn(BaseModel):
    entity: str
    metric: str
    period: str
    value: Decimal
    unit: str
    document_id: str
    page: int
    quote: str
    scale: Decimal = Decimal(1)
    basis: str = "GAAP"


@app.post("/facts", status_code=201)
def create_fact(body: FactIn, db: Db, tenant: Tenant):
    try:
        f = add_verified_fact(db, tenant_id=tenant, **body.model_dump())
    except CitationError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, tenant, "api", "fact.create", {"fact_id": f.id, "entity": body.entity,
                                                 "metric": body.metric, "period": body.period})
    return {"id": f.id, "status": f.status}


@app.get("/memo")
def memo(entity: str, db: Db, tenant: Tenant):
    return {"entity": entity, "markdown": build_memo(db, tenant, entity)}


@app.get("/search")
def search(q: str, db: Db, tenant: Tenant, doc_id: str | None = None, k: int = 5):
    if doc_id:
        _own_doc(db, tenant, doc_id)
    query = (db.query(PageRow).join(Document, Document.id == PageRow.document_id)
             .filter(Document.tenant_id == tenant))  # tenant filter BEFORE ranking
    if doc_id:
        query = query.filter(PageRow.document_id == doc_id)
    rows = query.all()
    index = PageIndex([(r.document_id, r.number, r.text) for r in rows])
    text = {(r.document_id, r.number): r.text for r in rows}
    return [{"document_id": h.doc_id, "page": h.page, "score": round(h.score, 3),
             "snippet": text[(h.doc_id, h.page)][:300]}
            for h in index.search(q, k=k, doc_ids={doc_id} if doc_id else None)]


class CompanyIn(BaseModel):
    name: str
    sector: str | None = None
    ownership_pct: Decimal | None = None


@app.post("/portfolio/companies", status_code=201)
def create_company(body: CompanyIn, db: Db, tenant: Tenant):
    c = PortfolioCompany(tenant_id=tenant, **body.model_dump())
    db.add(c)
    db.commit()
    log_event(db, tenant, "api", "company.create", {"company_id": c.id, "name": c.name})
    return {"id": c.id, "name": c.name}


@app.post("/portfolio/companies/{company_id}/observations", status_code=201)
def add_observation(company_id: int, fact_id: int, db: Db, tenant: Tenant):
    try:
        o = record_observation(db, tenant, company_id, fact_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, tenant, "api", "kpi.record", {"observation_id": o.id, "fact_id": fact_id})
    return {"id": o.id, "metric": o.metric, "period": o.period, "value": str(o.value)}


@app.get("/portfolio/companies/{company_id}/kpis")
def kpis(company_id: int, db: Db, tenant: Tenant):
    return [{"metric": o.metric, "period": o.period, "value": str(o.value), "unit": o.unit,
             "fact_id": o.fact_id} for o in current_kpis(db, tenant, company_id)]


@app.get("/portfolio/companies/{company_id}/change")
def change(company_id: int, metric: str, new: str, old: str, db: Db, tenant: Tenant):
    v = qoq_change(db, tenant, company_id, metric, new, old)
    return {"metric": metric, "new": new, "old": old,
            "pct_change": None if v is None else str(v.quantize(Decimal("0.01")))}


@app.get("/audit/verify")
def audit_verify(db: Db, tenant: Tenant):
    ok, bad = verify_chain(db, tenant)
    return {"ok": ok, "first_bad_id": bad}


def get_companyfacts(cik: int) -> dict:
    """Dependency so tests and offline deployments can supply cached JSON."""
    return fetch_companyfacts(cik)


@app.get("/xbrl/check")
def xbrl_check(cik: int, concept: str, end: str, value: Decimal, tenant: Tenant,
               start: str | None = None, accn: str | None = None, unit: str | None = "USD"):
    """Confirm a figure against the filer's own XBRL. Reports restatements instead of picking one."""
    try:
        facts = load_companyfacts(get_companyfacts(cik))
    except Exception as e:  # network / missing key / unknown CIK: say so, never guess
        raise HTTPException(502, f"companyfacts unavailable: {e}") from e
    res = crosscheck(value, candidates(facts, concept, end, start, accn, unit))
    return {"status": res.status, "distinct_values": [str(v) for v in res.distinct_values],
            "filings": sorted({f"{f.accn} ({f.form}, filed {f.filed})" for f in res.matched})}


def llm_dependency() -> LLM:
    try:
        return get_llm()
    except NoLLMConfigured as e:
        raise HTTPException(503, str(e)) from e


class AskIn(BaseModel):
    question: str
    doc_id: str | None = None


@app.post("/ask")
def ask(body: AskIn, db: Db, tenant: Tenant, llm: Annotated[LLM, Depends(llm_dependency)]):
    if body.doc_id:
        _own_doc(db, tenant, body.doc_id)
    a = answer_question(db, tenant, llm, body.question, body.doc_id)
    log_event(db, tenant, "api", "ask", {"question": body.question, "status": a.status,
                                         "claims": len(a.claims), "rejected": len(a.rejected)})
    cite = lambda c: {"text": c.text, "document_id": c.doc_id, "page": c.page, "quote": c.quote}
    return {"status": a.status, "detail": a.detail, "claims": [cite(c) for c in a.claims],
            "rejected": [{**cite(c), "reason": c.reason} for c in a.rejected]}
