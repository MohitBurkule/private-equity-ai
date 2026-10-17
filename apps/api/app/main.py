import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import date as DateT
from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import (
    add_on,
    enrich,
    notify,
    opendata_tools,  # noqa: F401  (registers open-data agent tools)
)
from app import agent as ag
from app import alerts as al
from app import ch_search as chs_mod
from app import companies_house as ch_mod
from app import comps as comps_mod
from app import covenant_parse as covparse_mod
from app import debt_parse as debt_parse_mod
from app import firm_knowledge as fk
from app import html_doc as html_doc_mod
from app import jobs as jobs_mod
from app import lbo as lbo_mod
from app import legal as legal_mod
from app import notify as notify_mod
from app import outreach as outreach_mod
from app import precedent_fetch as pfetch_mod
from app import precedents as prec_mod
from app import research as research_mod
from app import seen_before as seen_mod
from app import sourcing_search as ss_mod
from app import targets as tg_mod
from app import workflows as wf_mod
from app.acl import (
    Principal,
    deal_hidden,
    doc_visible,
    fact_visible,
    hidden_deal_names,
    visible_doc_ids,
    visible_mnpi_deal_names,
)
from app.answer import answer_question
from app.audit import log_event, verify_chain
from app.auth import (
    add_key,
    admin_token_ok,
    create_tenant,
    hash_key,
    key_id,
    principal_for_key,
    revoke_key,
)
from app.calc import Calc, find_conflicts, ltm, net_debt, nwc
from app.chat_alerts import chat_poster
from app.connectors import oauth, vault
from app.connectors.base import ConnectorError, default_http
from app.connectors.gsheets import GoogleSheets
from app.connectors.linkedin import LinkedInExport
from app.connectors.oauth import OAuthError
from app.connectors.registry import IMPLEMENTED, status
from app.connectors.sync import sync as connector_sync
from app.db import make_engine, make_session_factory
from app.dd import STATUSES, TEMPLATE
from app.edgar import fetch_companyfacts
from app.email_links import links_for
from app.extract.run import extract_schema
from app.extract.schemas import SCHEMAS
from app.extract.tieout import tie_out
from app.facts import CitationError, add_html_fact, add_verified_fact, review_fact
from app.factsxlsx import build_facts_xlsx, fact_rows
from app.filing_view import filing_page_html
from app.fundmetrics import fund_metrics
from app.holdings import parse_holdings
from app.hybrid import default_index
from app.ingest import finalize_upload, ingest_any
from app.ixbrl_full import read_filing
from app.llm import LLM, NoLLMConfigured, get_llm
from app.memo import build_memo, build_memo_docx, build_memo_pptx
from app.migrate import migrate
from app.models import (
    STAGES,
    AgentRun,
    Alert,
    Connection,
    DDRequest,
    Deal,
    DealChecklistItem,
    Document,
    DocumentFile,
    DocumentSource,
    EvalRun,
    Fact,
    FactSource,
    Holding,
    HtmlUnit,
    IngestJob,
    PageRow,
    Target,
    WorkflowSchedule,
)
from app.models import Tenant as TenantRow
from app.oidc import oidc_principal
from app.page_image import render_page
from app.parse.sh01 import parse_capital_form
from app.portfolio import (
    Covenant,
    PortfolioCompany,
    add_covenant,
    current_kpis,
    evaluate_covenant,
    qoq_change,
    record_observation,
)
from app.ratelimit import limiter
from app.report import build_report, build_report_docx
from app.rls import apply_rls, bind_tenant, install_tenant_hook, verify_app_role
from app.shareledger import Event as LedgerEvent
from app.shareledger import reconcile as reconcile_shares
from app.sumcheck import sum_check
from app.tracing import render_metrics, tracing_middleware
from app.waterfall import PrefClass, waterfall
from app.xbrl import candidates, crosscheck, load_companyfacts

engine = make_engine()
SessionLocal = make_session_factory(engine)
install_tenant_hook(SessionLocal)
# Schema + RLS run as the owner role (MIGRATE_DATABASE_URL); requests run as the app role.
_owner = make_engine(os.environ.get("MIGRATE_DATABASE_URL")) if os.environ.get("MIGRATE_DATABASE_URL") else engine
migrate(_owner)
apply_rls(_owner, os.environ.get("APP_DB_ROLE"))
verify_app_role(engine)

jobs_mod.requeue_pending(SessionLocal)
notify.start_periodic_scan(SessionLocal)
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

app = FastAPI(title="PE Platform API", version="0.0.1")
app.middleware("http")(tracing_middleware)


def get_db():
    with SessionLocal() as s:
        yield s


Db = Annotated[Session, Depends(get_db)]


def get_principal(db: Db, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    # A JWT has two dots; anything else is an API key. Keys keep working alongside SSO.
    p = oidc_principal(db, token) if token.count(".") == 2 else principal_for_key(db, token)
    if p is None:
        raise HTTPException(401, "invalid token")
    if not limiter.allow(p.tenant):
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "10"})
    bind_tenant(db, p.tenant)
    return p


Who = Annotated[Principal, Depends(get_principal)]


def get_tenant(p: Who) -> str:
    return p.tenant


def writer(p: Who) -> Principal:
    if not p.can_anywhere("write"):
        raise HTTPException(403, "role is read-only")
    return p


def _require(p: Principal, capability: str, what: str, deal: str | None = None) -> None:
    """Checks the key's role, or the role it holds on `deal` when one is given. Routes that take a deal name
    pass it, so a per-deal override applies to that deal only."""
    if not p.can(capability, deal):
        raise HTTPException(403, f"role {p.role_on(deal)} cannot {what}")


Writer = Annotated[Principal, Depends(writer)]
Tenant = Annotated[str, Depends(get_tenant)]


def actor(p: Principal) -> str:
    return f"key:{p.key_id}"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics(x_admin_token: Annotated[str | None, Header()] = None):
    """Prometheus text: request counts by method, route template and status class, plus summed latency."""
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    return Response(render_metrics(), media_type="text/plain; version=0.0.4")


class TenantIn(BaseModel):
    name: str


@app.post("/admin/tenants", status_code=201)
def admin_create_tenant(body: TenantIn, db: Db, x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    t, key = create_tenant(db, body.name)
    return {"tenant_id": t.id, "api_key": key, "key_id": key_id(hash_key(key)),
            "note": "store this key now; it is not shown again"}


class KeyIn(BaseModel):
    role: str = "analyst"
    deals: list[str] | None = None  # None = unrestricted; [] = sees nothing
    deal_roles: dict[str, str] | None = None  # per-deal role overrides, e.g. {"atlas": "partner"}


@app.post("/admin/tenants/{tenant_id}/keys", status_code=201)
def admin_add_key(tenant_id: str, db: Db, body: KeyIn | None = None, x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    if db.get(TenantRow, tenant_id) is None:
        raise HTTPException(404, "tenant not found")
    body = body or KeyIn()
    try:
        kid, key = add_key(db, tenant_id, body.role, body.deals, body.deal_roles)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"key_id": kid, "role": body.role, "deals": body.deals, "deal_roles": body.deal_roles, "api_key": key,
            "note": "store this key now; it is not shown again"}


@app.delete("/admin/keys/{kid}")
def admin_revoke_key(kid: str, db: Db, x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    if not revoke_key(db, kid):
        raise HTTPException(404, "key not found")
    return {"revoked": kid}


@app.post("/documents")
async def upload(file: Annotated[UploadFile, File()], db: Db, who: Who,
                 deal: Annotated[str | None, Form()] = None):
    tenant = who.tenant
    deal = (deal or "").strip() or None
    if who.restricted and deal not in who.deals:
        raise HTTPException(403, "deal is required and must be within this key's scope")
    _require(who, "upload", "upload documents", deal=deal)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    res = ingest_any(db, tenant, data, file.filename or "upload.pdf")
    kept, skipped = finalize_upload(db, who, res, deal)
    if not kept:  # nothing usable: keep the old single-file error contract
        reason = skipped[0]["reason"] if skipped else "no documents"
        code = 409 if "already stored" in reason else 422
        raise HTTPException(code, reason if code == 409 else f"cannot parse file: {reason}")
    for doc in kept:
        log_event(db, tenant, actor(who), "document.upload",
                  {"document_id": doc.id, "filename": doc.filename, "deal": doc.deal})
    first = kept[0]
    out = {"id": first.id, "filename": first.filename, "n_pages": first.n_pages, "deal": first.deal}
    if len(kept) > 1 or skipped:
        out["documents"] = [{"id": d.id, "filename": d.filename, "n_pages": d.n_pages, "kind": d.kind} for d in kept]
        out["skipped"] = skipped
    return out


@app.post("/documents/async", status_code=202)
async def upload_async(file: Annotated[UploadFile, File()], db: Db, who: Who,
                       deal: Annotated[str | None, Form()] = None):
    """Same rules as /documents, but parsing happens in the background. Poll GET /jobs/{id}."""
    deal = (deal or "").strip() or None
    if who.restricted and deal not in who.deals:
        raise HTTPException(403, "deal is required and must be within this key's scope")
    _require(who, "upload", "upload documents", deal=deal)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    job = jobs_mod.submit(db, who, data, file.filename or "upload.pdf", deal, SessionLocal)
    return {"job_id": job.id, "status": job.status}


def _job_out(j: IngestJob) -> dict:
    import json as _json
    return {"job_id": j.id, "filename": j.filename, "status": j.status, "stage": j.stage, "attempts": j.attempts,
            "error": j.error, "created_at": j.created_at, "updated_at": j.updated_at,
            "result": _json.loads(j.result) if j.result else None}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, db: Db, who: Who):
    j = db.get(IngestJob, job_id)
    if j is None or j.tenant_id != who.tenant or (who.restricted and j.key_id != who.key_id):
        raise HTTPException(404, "job not found")  # walled keys see only their own jobs
    return _job_out(j)


@app.get("/jobs")
def list_jobs(db: Db, who: Who):
    q = db.query(IngestJob).filter_by(tenant_id=who.tenant)
    if who.restricted:
        q = q.filter_by(key_id=who.key_id)
    return [_job_out(j) for j in q.order_by(IngestJob.created_at.desc()).limit(100).all()]


@app.post("/admin/jobs/requeue")
def admin_requeue(x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    return {"requeued": jobs_mod.requeue_pending(SessionLocal)}


def _own_doc(db: Session, who: Principal, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if not doc_visible(doc, who, hidden_deal_names(db, who)):  # same 404 for "missing", "other tenant", "behind a wall"
        raise HTTPException(404, "document not found")
    if doc.deal and doc.deal in visible_mnpi_deal_names(db, who):
        log_event(db, who.tenant, actor(who), "document.mnpi_access", {"doc_id": doc.id, "deal": doc.deal})
        db.commit()
    return doc


def _value_out(v) -> dict | None:
    if v is None:
        return None
    return {"value": str(v.value), "page": v.page, "quote": v.quote, "ocr": v.ocr, "readable": v.readable}


@app.get("/documents/{doc_id}/capital-form")
def capital_form(doc_id: str, db: Db, who: Who):
    """Read a Companies House SH01 from the stored pages. Every value has its page and quote; values from
    OCR pages are flagged and must be confirmed by a person before they are used as facts."""
    doc = _own_doc(db, who, doc_id)
    rows = db.query(PageRow).filter_by(document_id=doc.id).order_by(PageRow.number).all()
    f = parse_capital_form([(r.number, r.text, r.method == "ocr") for r in rows])
    row = lambda a: {"class": _value_out(a.cls), "number": _value_out(a.number), "nominal": _value_out(a.nominal),
                     "paid": _value_out(a.paid), "unpaid": _value_out(a.unpaid)}
    return {"form": f.form, "company_number": _value_out(f.company_number),
            "date_from": _value_out(f.date_from), "date_to": _value_out(f.date_to),
            "allotments": [row(a) for a in f.allotments], "statement_rows": [row(a) for a in f.statement_rows],
            "total_shares": _value_out(f.total_shares), "total_nominal": _value_out(f.total_nominal),
            "problems": f.problems}


@app.get("/documents/{doc_id}/pages/{number}/image")
def get_page_image(doc_id: str, number: int, db: Db, who: Who, quote: str = Query("", max_length=1000)):
    """The page as filed, PNG, with the quote highlighted when it is found on the page."""
    _own_doc(db, who, doc_id)
    original = db.get(DocumentFile, doc_id)
    if original is None or original.media_type != "application/pdf":
        raise HTTPException(404, "no PDF kept for this document")
    if number < 1 or number > db.query(PageRow).filter_by(document_id=doc_id).count():
        raise HTTPException(404, "page not found")
    png, highlighted = render_page(original.data, number, quote)
    return Response(png, media_type="image/png", headers={"X-Quote-Highlighted": "1" if highlighted else "0"})


@app.post("/documents/{doc_id}/capital-form/facts", status_code=201)
def capital_form_facts(doc_id: str, db: Db, who: Writer):
    """Store each readable SH01 allotment as a fact (shares allotted per class and period). Each goes
    through the citation gate: its number must appear in its quote on the cited page. OCR pages are
    stored as ocr_unverified, so they wait in the review queue."""
    doc = _own_doc(db, who, doc_id)
    rows = db.query(PageRow).filter_by(document_id=doc.id).order_by(PageRow.number).all()
    f = parse_capital_form([(r.number, r.text, r.method == "ocr") for r in rows])
    entity = f.company_number.value if f.company_number and f.company_number.readable else doc.filename
    period = str(f.date_to.value) if f.date_to and f.date_to.readable else "unknown"
    created, skipped = [], []
    for a in f.allotments:
        n = a.number
        if not n.readable or not isinstance(n.value, Decimal):
            skipped.append({"class": a.cls.value, "reason": "allotted number not readable"})
            continue
        try:
            fact = add_verified_fact(db, tenant_id=who.tenant, entity=str(entity), metric=f"shares allotted {a.cls.value}",
                                     period=period, value=n.value, unit="shares", document_id=doc.id,
                                     page=n.page, quote=n.quote)
        except CitationError as e:
            skipped.append({"class": a.cls.value, "reason": str(e)})
            continue
        created.append(fact.id)
    log_event(db, who.tenant, actor(who), "capital_form.facts", {"document_id": doc.id, "created": created})
    return {"created": created, "skipped": skipped, "problems": f.problems}


@app.post("/documents/{doc_id}/credit-agreement/facts", status_code=201)
def credit_agreement_facts(doc_id: str, db: Db, who: Writer):
    """Store covenant thresholds and facility amounts read from a credit agreement as facts. Each one goes
    through the citation gate. PDFs cite a page and the quote on it. HTML filings cite the text block: its
    section, anchor and character offset. A facility named only through a defined term (e.g. "Loans") is cited
    with the amount sentence and the definition chain that names the facility. Duplicates are stored once."""
    doc = _own_doc(db, who, doc_id)
    html = doc.kind == "html"
    if html:
        units = db.query(HtmlUnit).filter_by(document_id=doc.id).order_by(HtmlUnit.idx).all()
        pages = [(u.idx, u.text) for u in units]
        by_key = {u.idx: u for u in units}
    else:
        rows = db.query(PageRow).filter_by(document_id=doc.id).order_by(PageRow.number).all()
        pages = [(r.number, r.text) for r in rows]
    entity = doc.deal or doc.filename
    # (metric, unit, value, locator key, quote, extra (key, quote) sources)
    candidates = []
    for c in covparse_mod.extract(pages):
        word = "maximum" if c["operator"] == "<=" else "minimum"
        candidates.append((f"covenant {c['kpi_metric']} {word}", "x", Decimal(c["threshold"]), c["page"], c["quote"], []))
    for t in debt_parse_mod.extract(pages):
        candidates.append((f"facility amount {t['facility']}", "USD", t["amount"], t["page"], t["quote"], []))
    if html:
        for t in html_doc_mod.defined_facility_amounts(units):
            candidates.append((f"facility amount {t['facility']}", "USD", Decimal(t["amount"]), t["idx"], t["quote"],
                               t["extra_sources"]))
    for g in debt_parse_mod.margin_grid(pages):
        tier = f"level {g['level']} ({g['leverage_test']})"
        candidates.append((f"Term SOFR margin {tier}", "%", Decimal(g["sofr_pct"]), g["page"], g["quote"], []))
        candidates.append((f"Base Rate margin {tier}", "%", Decimal(g["base_pct"]), g["page"], g["quote"], []))
    created, skipped, seen = [], [], set()
    for metric, unit, value, key, quote, extra in candidates:
        if (metric, value, key, quote) in seen:
            continue
        seen.add((metric, value, key, quote))
        try:
            if html:
                fact = add_html_fact(db, tenant_id=who.tenant, entity=entity, metric=metric, period="per agreement",
                                     value=value, unit=unit, document_id=doc.id,
                                     sources=[(key, quote), *extra])
            else:
                fact = add_verified_fact(db, tenant_id=who.tenant, entity=entity, metric=metric,
                                         period="per agreement", value=value, unit=unit, document_id=doc.id,
                                         page=key, quote=quote)
        except CitationError as e:
            skipped.append({"metric": metric, "reason": str(e), "location": _locate(by_key, key) if html else {"page": key}})
            continue
        created.append(fact.id)
    log_event(db, who.tenant, actor(who), "credit_agreement.facts", {"document_id": doc.id, "created": created})
    # Maturity is a defined tenor, not a number, so it is returned cited and not stored as a fact.
    maturity = debt_parse_mod.maturity_clauses(pages)
    if html:
        for m in maturity:
            m["location"] = _locate(by_key, m.pop("page"))
    return {"created": created, "skipped": skipped, "maturity_clauses": maturity}


def _locate(by_key: dict[int, HtmlUnit], idx: int) -> dict:
    u = by_key[idx]
    return {"section": u.section, "heading": u.heading, "anchor": u.anchor, "offset": u.offset}


@lru_cache(maxsize=4)
def _filing_tags(data: bytes):
    return read_filing(data.decode("utf-8", errors="replace"))[1]


@app.get("/documents/{doc_id}/pages/{number}/html")
def get_page_html(doc_id: str, number: int, db: Db, who: Who, quote: str = Query("", max_length=1000),
                  anchor: str | None = Query(None, max_length=200), offset: int | None = Query(None, ge=0)):
    """A filing page as filed, with the target highlighted and scrollable. The target is the element with
    id `anchor`, or the character `offset` in the filing, when given; otherwise the figure matching `quote`."""
    _own_doc(db, who, doc_id)
    original = db.get(DocumentFile, doc_id)
    if original is None or original.media_type != "text/html":
        raise HTTPException(404, "no filing HTML kept for this document")
    html = original.data.decode("utf-8", errors="replace")
    shown = filing_page_html(html, _filing_tags(original.data), number, quote, anchor, offset)
    if shown is None:
        raise HTTPException(404, "no target on this page")
    doc, highlighted = shown
    return Response(doc, media_type="text/html; charset=utf-8", headers={
        "X-Quote-Highlighted": "1" if highlighted else "0",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.get("/documents/{doc_id}/pages/{number}")
def get_page(doc_id: str, number: int, db: Db, who: Who):
    _own_doc(db, who, doc_id)
    row = db.query(PageRow).filter_by(document_id=doc_id, number=number).one_or_none()
    if row is None:
        raise HTTPException(404, "page not found")
    return {"document_id": doc_id, "page": number, "text": row.text, "method": row.method,
            "ocr_confidence": row.ocr_confidence}


@app.get("/documents")
def list_documents(db: Db, who: Who):
    hidden = hidden_deal_names(db, who)
    return [{"id": d.id, "filename": d.filename, "n_pages": d.n_pages, "deal": d.deal}
            for d in db.query(Document).filter_by(tenant_id=who.tenant).all() if doc_visible(d, who, hidden)]


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
def create_fact(body: FactIn, db: Db, who: Writer):
    tenant = who.tenant
    _own_doc(db, who, body.document_id)
    try:
        f = add_verified_fact(db, tenant_id=tenant, **body.model_dump())
    except CitationError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, tenant, actor(who), "fact.create", {"fact_id": f.id, "entity": body.entity,
                                                 "metric": body.metric, "period": body.period})
    return {"id": f.id, "status": f.status}


def _fact_out(f: Fact) -> dict:
    return {"id": f.id, "entity": f.entity, "metric": f.metric, "period": f.period, "value": str(f.value),
            "unit": f.unit, "basis": f.basis, "status": f.status, "reviewed_by": f.reviewed_by,
            "reviewed_at": f.reviewed_at, "review_note": f.review_note,
            "sources": [{"document_id": s.document_id, "page": s.page, "section": s.section, "heading": s.heading,
                         "quote": s.quote} for s in f.sources]}


@app.get("/facts")
def list_facts(db: Db, who: Who, status: str | None = None, entity: str | None = None):
    """Review queue: filter by status (e.g. ocr_unverified) to see what still needs a human."""
    q = db.query(Fact).filter_by(tenant_id=who.tenant)
    if status:
        q = q.filter_by(status=status)
    if entity:
        q = q.filter_by(entity=entity)
    scope = visible_doc_ids(db, who)
    return [_fact_out(f) for f in q.order_by(Fact.id).all() if fact_visible(f, scope)]


class ReviewIn(BaseModel):
    action: str  # accept | reject | edit
    note: str | None = None
    value: Decimal | None = None
    page: int | None = None
    quote: str | None = None
    scale: Decimal = Decimal(1)


@app.post("/facts/{fact_id}/review")
def review(fact_id: int, body: ReviewIn, db: Db, who: Writer):
    f = db.get(Fact, fact_id)
    if f is None or f.tenant_id != who.tenant or not fact_visible(f, visible_doc_ids(db, who)):
        raise HTTPException(404, "fact not found")
    before = {"status": f.status, "value": str(f.value), "page": f.sources[0].page, "quote": f.sources[0].quote}
    try:
        review_fact(db, f, action=body.action, reviewer=actor(who), note=body.note, value=body.value,
                    page=body.page, quote=body.quote, scale=body.scale)
    except CitationError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "fact.review",
              {"fact_id": f.id, "action": body.action, "before": before, "after": _fact_out(f), "note": body.note})
    return _fact_out(f)


def _calc_out(c: Calc) -> dict:
    return {"name": c.name, "entity": c.entity, "ok": c.ok, "value": None if c.value is None else str(c.value),
            "unit": c.unit, "formula": c.formula, "missing": c.missing, "problems": c.problems,
            "inputs": [{"role": i.role, "sign": i.sign, "fact_id": i.fact.id, "metric": i.fact.metric,
                        "period": i.fact.period, "value": str(i.fact.value), "unit": i.fact.unit,
                        "sources": [{"document_id": s.document_id, "page": s.page, "section": s.section,
                                     "heading": s.heading, "quote": s.quote} for s in i.fact.sources]}
                       for i in c.inputs]}


@app.get("/facts/conflicts")
def fact_conflicts(db: Db, who: Who, entity: str | None = None, cross_document_only: bool = False):
    """Same entity, metric, period and basis with different values across facts. Reports only."""
    return [{"entity": c.entity, "metric": c.metric, "period": c.period, "basis": c.basis,
             "spread_pct": str(c.spread_pct.quantize(Decimal("0.01"))), "likely_rounding": c.likely_rounding,
             "severity": c.severity, "cross_document": c.cross_document, "sources": c.sources,
             "values": [{"value": str(v), "fact_id": fid} for v, fid in c.values]}
            for c in find_conflicts(db, who.tenant, visible_doc_ids(db, who), entity)
            if c.cross_document or not cross_document_only]


@app.post("/lbo/returns")
def lbo_returns(body: dict, db: Db, who: Who, xlsx: bool = False):
    """Sponsor returns from cited inputs. Each input is {"value", "source": {document_id, page, quote}}
    or {"fact_id"}; an uncited input is refused."""
    raw = body.get("inputs") or {}
    scope = visible_doc_ids(db, who)
    cited: dict[str, lbo_mod.Cited] = {}
    for name, spec in raw.items():
        if "fact_id" in spec:
            f = db.query(Fact).filter(Fact.id == spec["fact_id"], Fact.tenant_id == who.tenant).first()
            if f is None or not fact_visible(f, scope) or not f.sources or f.status != "verified":
                raise HTTPException(422, f"{name}: fact not found, not verified, or has no source")
            names = {d.id: d.filename for d in db.query(Document).filter(
                Document.id.in_({s.document_id for s in f.sources}))}
            src = {"document_id": f.sources[0].document_id, "filename": names.get(f.sources[0].document_id),
                   "page": f.sources[0].page, "quote": f.sources[0].quote}
            cited[name] = lbo_mod.Cited(f.value, src)
        else:
            src = spec.get("source") or {}
            if not src.get("document_id") or not src.get("quote") or not src.get("page"):
                raise HTTPException(422, f"{name}: citation needs document_id, page and quote")
            cited[name] = lbo_mod.Cited(Decimal(str(spec["value"])), src)
    unknown = set(cited) - set(lbo_mod.REQUIRED) - set(lbo_mod.OPTIONAL)
    if unknown:
        raise HTTPException(422, f"unknown inputs: {', '.join(sorted(unknown))}")
    if lbo_mod.missing(cited):
        raise HTTPException(422, f"missing inputs: {', '.join(lbo_mod.missing(cited))}")
    try:
        res = lbo_mod.run(cited)
        grid = None
        if body.get("entry_multiples") and body.get("exit_multiples"):
            grid = lbo_mod.sensitivity(cited, [Decimal(str(x)) for x in body["entry_multiples"]],
                                       [Decimal(str(x)) for x in body["exit_multiples"]])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if xlsx:
        return Response(lbo_mod.build_xlsx(cited, res, grid), headers={
            "Content-Disposition": 'attachment; filename="lbo_returns.xlsx"'},
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return {"entry_ev": str(res.entry_ev), "debt": str(res.debt), "fees": str(res.fees),
            "equity": str(res.equity), "exit_ev": str(res.exit_ev), "exit_net_debt": str(res.exit_net_debt),
            "exit_equity": str(res.exit_equity), "moic": str(res.moic.quantize(Decimal("0.01"))),
            "irr": None if res.irr is None else str(res.irr.quantize(Decimal("0.0001"))),
            "dividends": str(res.dividends), "schedule": res.schedule, "sensitivity": grid}


@app.get("/calc/ltm")
def calc_ltm(entity: str, metric: str, fy: str, ytd: str, ytd_prior: str, db: Db, who: Who):
    return _calc_out(ltm(db, who.tenant, entity, metric, fy, ytd, ytd_prior, visible_doc_ids(db, who)))


@app.get("/calc/net-debt")
def calc_net_debt(entity: str, period: str, db: Db, who: Who, include_leases: bool = True):
    return _calc_out(net_debt(db, who.tenant, entity, period, visible_doc_ids(db, who), include_leases))


@app.get("/calc/nwc")
def calc_nwc(entity: str, period: str, db: Db, who: Who):
    return _calc_out(nwc(db, who.tenant, entity, period, visible_doc_ids(db, who)))


def _dd_scope_ok(who: Principal, deal: str) -> bool:
    return who.deals is None or deal in who.deals


def _dd_out(r: DDRequest) -> dict:
    return {"id": r.id, "deal": r.deal, "category": r.category, "title": r.title, "status": r.status,
            "document_id": r.document_id, "note": r.note, "updated_at": r.updated_at}


class DDSeed(BaseModel):
    deal: str
    categories: list[str] | None = None  # None = all template categories


class DDItem(BaseModel):
    deal: str
    category: str
    title: str


class DDUpdate(BaseModel):
    status: str | None = None
    document_id: str | None = None
    note: str | None = None


@app.post("/dd/requests/seed", status_code=201)
def dd_seed(body: DDSeed, db: Db, who: Writer):
    """Create the standard request list for a deal. Existing titles are not duplicated."""
    if not _dd_scope_ok(who, body.deal):
        raise HTTPException(403, "deal is outside this key's scope")
    cats = body.categories or list(TEMPLATE)
    bad = [c for c in cats if c not in TEMPLATE]
    if bad:
        raise HTTPException(422, f"unknown categories: {bad}; available: {sorted(TEMPLATE)}")
    have = {r.title for r in db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=body.deal)}
    n = 0
    for cat in cats:
        for title in TEMPLATE[cat]:
            if title not in have:
                db.add(DDRequest(tenant_id=who.tenant, deal=body.deal, category=cat, title=title,
                                 updated_at=_now_iso()))
                n += 1
    db.commit()
    log_event(db, who.tenant, actor(who), "dd.seed", {"deal": body.deal, "created": n})
    return {"created": n}


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


@app.post("/dd/requests", status_code=201)
def dd_add(body: DDItem, db: Db, who: Writer):
    if not _dd_scope_ok(who, body.deal):
        raise HTTPException(403, "deal is outside this key's scope")
    r = DDRequest(tenant_id=who.tenant, deal=body.deal, category=body.category, title=body.title,
                  updated_at=_now_iso())
    db.add(r)
    db.commit()
    return _dd_out(r)


@app.get("/dd/requests")
def dd_list(db: Db, who: Who, deal: str | None = None, status: str | None = None):
    q = db.query(DDRequest).filter_by(tenant_id=who.tenant)
    if deal:
        q = q.filter_by(deal=deal)
    if status:
        q = q.filter_by(status=status)
    return [_dd_out(r) for r in q.order_by(DDRequest.id).all() if _dd_scope_ok(who, r.deal)]


@app.patch("/dd/requests/{rid}")
def dd_update(rid: int, body: DDUpdate, db: Db, who: Writer):
    r = db.get(DDRequest, rid)
    if r is None or r.tenant_id != who.tenant or not _dd_scope_ok(who, r.deal):
        raise HTTPException(404, "request not found")
    if body.status is not None and body.status not in STATUSES:
        raise HTTPException(422, f"status must be one of {STATUSES}")
    if body.document_id is not None:
        doc = db.get(Document, body.document_id)
        if not doc_visible(doc, who, hidden_deal_names(db, who)):
            raise HTTPException(404, "document not found")
        if doc.deal != r.deal:
            raise HTTPException(422, "document belongs to a different deal")
        r.document_id = doc.id
        r.status = body.status or "received"  # attaching a document means it arrived
    elif body.status is not None:
        r.status = body.status
    if body.note is not None:
        r.note = body.note
    r.updated_at = _now_iso()
    db.commit()
    log_event(db, who.tenant, actor(who), "dd.update", {"request_id": r.id, "status": r.status,
                                                         "document_id": r.document_id})
    return _dd_out(r)


@app.get("/dd/summary")
def dd_summary(deal: str, db: Db, who: Who):
    """Counts per category and the list of items still open: the missing-document tracker."""
    if not _dd_scope_ok(who, deal):
        raise HTTPException(404, "deal not found")
    rows = db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=deal).all()
    cats: dict[str, dict[str, int]] = {}
    for r in rows:
        c = cats.setdefault(r.category, {"open": 0, "received": 0, "waived": 0})
        c[r.status] += 1
    done = sum(r.status != "open" for r in rows)
    return {"deal": deal, "total": len(rows), "closed": done,
            "pct_complete": round(100 * done / len(rows), 1) if rows else None,
            "by_category": cats, "missing": [_dd_out(r) for r in rows if r.status == "open"]}


class DealIn(BaseModel):
    name: str
    stage: str = "sourcing"
    note: str | None = None
    mnpi: bool = False


class DealUpdate(BaseModel):
    stage: str | None = None
    note: str | None = None
    legal_hold: bool | None = None
    mnpi: bool | None = None


def _deal_out(db: Session, who: Principal, d: Deal) -> dict:
    dd = db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=d.name).all()
    docs = db.query(Document).filter_by(tenant_id=who.tenant, deal=d.name).count()
    closed = sum(r.status != "open" for r in dd)
    return {"name": d.name, "stage": d.stage, "note": d.note, "legal_hold": d.legal_hold, "mnpi": d.mnpi, "updated_at": d.updated_at,
            "documents": docs, "dd_total": len(dd), "dd_open": len(dd) - closed}


@app.post("/deals", status_code=201)
def deal_create(body: DealIn, db: Db, who: Writer):
    if who.deals is not None:
        raise HTTPException(403, "walled keys cannot create deals")
    if body.mnpi:
        _require(who, "govern", "flag a deal MNPI")
    if body.stage not in STAGES:
        raise HTTPException(422, f"stage must be one of {STAGES}")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name required")
    if db.query(Deal).filter_by(tenant_id=who.tenant, name=name).first():
        raise HTTPException(409, "deal already exists")
    d = Deal(tenant_id=who.tenant, name=name, stage=body.stage, note=body.note, mnpi=body.mnpi,
             created_by=who.key_id if body.mnpi else None, updated_at=_now_iso())
    db.add(d)
    db.commit()
    log_event(db, who.tenant, actor(who), "deal.create", {"name": name, "stage": d.stage})
    return _deal_out(db, who, d)


@app.get("/deals")
def deal_list(db: Db, who: Who):
    rows = db.query(Deal).filter_by(tenant_id=who.tenant).order_by(Deal.id).all()
    shown = [d for d in rows if _dd_scope_ok(who, d.name) and not deal_hidden(d, who)]
    mnpi_shown = [d.name for d in shown if d.mnpi]
    if mnpi_shown:
        log_event(db, who.tenant, actor(who), "deal.mnpi_access", {"deals": mnpi_shown, "via": "list"})
        db.commit()
    return [_deal_out(db, who, d) for d in shown]


class ChecklistIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)


class ChecklistUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    done: bool | None = None


def _checklist_out(r: DealChecklistItem) -> dict:
    return {"id": r.id, "deal": r.deal, "title": r.title, "done": r.done, "updated_at": r.updated_at}


def _visible_deal_or_404(db: Session, who: Principal, name: str) -> Deal:
    # Same visibility rules as the deal itself, so a checklist never leaks a walled or hidden deal.
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=name).first()
    if d is None or not _dd_scope_ok(who, name) or deal_hidden(d, who):
        raise HTTPException(404, "deal not found")
    return d


@app.get("/deals/{name}/checklist")
def checklist_list(name: str, db: Db, who: Who):
    _visible_deal_or_404(db, who, name)
    rows = db.query(DealChecklistItem).filter_by(tenant_id=who.tenant, deal=name).order_by(DealChecklistItem.id).all()
    return [_checklist_out(r) for r in rows]


@app.post("/deals/{name}/checklist", status_code=201)
def checklist_add(name: str, body: ChecklistIn, db: Db, who: Who):
    _visible_deal_or_404(db, who, name)
    _require(who, "write", "edit the checklist", deal=name)
    r = DealChecklistItem(tenant_id=who.tenant, deal=name, title=body.title.strip(), done=False, updated_at=_now_iso())
    db.add(r)
    db.commit()
    log_event(db, who.tenant, actor(who), "checklist.add", {"deal": name, "id": r.id})
    return _checklist_out(r)


@app.patch("/deals/{name}/checklist/{item_id}")
def checklist_update(name: str, item_id: int, body: ChecklistUpdate, db: Db, who: Who):
    _visible_deal_or_404(db, who, name)
    r = db.query(DealChecklistItem).filter_by(tenant_id=who.tenant, deal=name, id=item_id).first()
    if r is None:
        raise HTTPException(404, "checklist item not found")
    if body.title is not None:
        r.title = body.title.strip()
    if body.done is not None:
        r.done = body.done
    r.updated_at = _now_iso()
    db.commit()
    log_event(db, who.tenant, actor(who), "checklist.update", {"deal": name, "id": item_id, "done": r.done})
    return _checklist_out(r)


@app.delete("/deals/{name}/checklist/{item_id}", status_code=204)
def checklist_delete(name: str, item_id: int, db: Db, who: Who):
    _visible_deal_or_404(db, who, name)
    r = db.query(DealChecklistItem).filter_by(tenant_id=who.tenant, deal=name, id=item_id).first()
    if r is None:
        raise HTTPException(404, "checklist item not found")
    db.delete(r)
    db.commit()
    log_event(db, who.tenant, actor(who), "checklist.delete", {"deal": name, "id": item_id})


@app.patch("/deals/{name}")
def deal_update(name: str, body: DealUpdate, db: Db, who: Who):
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=name).first()
    if d is None or not _dd_scope_ok(who, name) or deal_hidden(d, who):
        raise HTTPException(404, "deal not found")
    # Compliance may hold and flag a deal without being able to change its analysis.
    if body.stage is not None or body.note is not None:
        _require(who, "write", "edit deal stage or notes", deal=name)
    if body.legal_hold is not None:
        _require(who, "govern", "change a legal hold", deal=name)
    if body.mnpi is not None:
        _require(who, "govern", "change the MNPI flag", deal=name)
        d.mnpi = body.mnpi
        if body.mnpi and d.created_by is None:
            d.created_by = who.key_id or None
    if body.stage is not None:
        if body.stage not in STAGES:
            raise HTTPException(422, f"stage must be one of {STAGES}")
        d.stage = body.stage
    if body.note is not None:
        d.note = body.note
    if body.legal_hold is not None:
        d.legal_hold = body.legal_hold
    d.updated_at = _now_iso()
    db.commit()
    log_event(db, who.tenant, actor(who), "deal.update", {"name": name, "stage": d.stage, "legal_hold": d.legal_hold})
    return _deal_out(db, who, d)


@app.delete("/deals/{name}")
def deal_delete(name: str, db: Db, who: Writer):
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=name).first()
    if d is None or not _dd_scope_ok(who, name) or deal_hidden(d, who):
        raise HTTPException(404, "deal not found")
    # Holds and linked documents are refused rather than cascaded: deleting evidence the team
    # still relies on is the one step here that cannot be walked back.
    _require(who, "govern", "delete deals", deal=name)
    if d.legal_hold:
        raise HTTPException(409, "deal is under legal hold")
    if db.query(Document).filter_by(tenant_id=who.tenant, deal=name).first():
        raise HTTPException(409, "documents still linked to this deal; unlink them first")
    removed = db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=name).delete()
    db.delete(d)
    db.commit()
    log_event(db, who.tenant, actor(who), "deal.delete", {"name": name, "dd_requests_removed": removed})
    return {"deleted": name, "dd_requests_removed": removed}


RETENTION_STAGES = ("closed", "passed")


def _retention_candidates(db: Session, who: Principal, older_than_days: int) -> list[Deal]:
    """Closed or passed deals untouched for longer than the cutoff. A deal with no recorded
    update time is never a candidate: unknown age fails closed."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    out = []
    for d in db.query(Deal).filter_by(tenant_id=who.tenant).order_by(Deal.id).all():
        if d.stage not in RETENTION_STAGES or d.legal_hold or not d.updated_at:
            continue
        if not _dd_scope_ok(who, d.name) or deal_hidden(d, who):
            continue
        updated = datetime.fromisoformat(d.updated_at)
        if updated.tzinfo is None:  # rows written before timestamps carried a zone are read as UTC
            updated = updated.replace(tzinfo=UTC)
        if updated < cutoff:
            out.append(d)
    return out


class RetentionIn(BaseModel):
    older_than_days: int = Field(ge=1)
    dry_run: bool = True


@app.post("/retention/deals")
def retention_deals(body: RetentionIn, db: Db, who: Writer):
    _require(who, "govern", "run retention purges")
    """Dry run lists what would go. A real run deletes candidates that have no linked documents
    and records each deletion in the audit chain. Holds and linked documents are always skipped."""
    cands = _retention_candidates(db, who, body.older_than_days)
    if body.dry_run:
        return {"dry_run": True, "candidates": [d.name for d in cands]}
    deleted, skipped = [], []
    for d in cands:
        if db.query(Document).filter_by(tenant_id=who.tenant, deal=d.name).first():
            skipped.append({"name": d.name, "reason": "documents still linked"})
            continue
        removed = db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=d.name).delete()
        db.delete(d)
        deleted.append(d.name)
        log_event(db, who.tenant, actor(who), "deal.retention_delete",
                  {"name": d.name, "older_than_days": body.older_than_days, "dd_requests_removed": removed})
    db.commit()
    return {"dry_run": False, "deleted": deleted, "skipped": skipped}


@app.post("/retention/documents")
def retention_documents(body: RetentionIn, db: Db, who: Writer):
    _require(who, "govern", "run retention purges")
    """Same rules as deal retention, for documents. Unknown creation time is never a candidate.
    A document cited by a fact or a DD item is kept, and a document on a held or walled deal is
    skipped whatever its age."""
    cutoff = datetime.now(UTC) - timedelta(days=body.older_than_days)
    hidden = hidden_deal_names(db, who)
    held = {d.name for d in db.query(Deal).filter_by(tenant_id=who.tenant, legal_hold=True)}
    cands = []
    for doc in db.query(Document).filter_by(tenant_id=who.tenant).order_by(Document.created_at).all():
        if not doc.created_at or not doc_visible(doc, who, hidden):
            continue
        if doc.deal and (doc.deal in held or doc.deal in hidden):
            continue
        created = datetime.fromisoformat(doc.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created < cutoff:
            cands.append(doc)
    if body.dry_run:
        return {"dry_run": True, "candidates": [d.id for d in cands]}
    deleted, skipped = [], []
    for doc in cands:
        if db.query(FactSource).filter_by(document_id=doc.id).first() or \
                db.query(DDRequest).filter_by(document_id=doc.id).first():
            skipped.append({"id": doc.id, "reason": "cited by a fact or DD item"})
            continue
        db.delete(doc)
        deleted.append(doc.id)
        log_event(db, who.tenant, actor(who), "document.retention_delete",
                  {"document_id": doc.id, "deal": doc.deal, "older_than_days": body.older_than_days})
    db.commit()
    return {"dry_run": False, "deleted": deleted, "skipped": skipped}


@app.get("/memo")
def memo(entity: str, db: Db, who: Who):
    return {"entity": entity, "markdown": build_memo(db, who.tenant, entity, visible_doc_ids(db, who))}


def get_sec_fetch():
    from app.secfeed import default_fetch
    return default_fetch


@app.get("/sec/filings")
def sec_filings(ticker: str, tenant: Tenant, fetch: Annotated[Callable, Depends(get_sec_fetch)]):
    from dataclasses import asdict

    from app.secfeed import recent_filings
    try:
        return [asdict(f) for f in recent_filings(ticker, fetch)]
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


def get_ch_fetch():
    from app.chfeed import default_fetch
    return default_fetch


def get_market_fetch():
    from app.marketfeeds import default_fetch
    return default_fetch


@app.get("/market/quote")
def market_quote(symbol: str, provider: str, who: Who, fetch: Annotated[Callable, Depends(get_market_fetch)],
                 currency: str | None = None):
    """Latest price from a named provider: yahoo, stooq (needs `currency`) or factset (needs credentials).
    Returns the source's own as-of date; 404 when the source has nothing, never a made-up number."""
    from app import marketfeeds
    from app.marketdata import NoData

    try:
        if provider == "stooq":
            if not currency:
                raise HTTPException(422, "stooq quotes carry no currency; pass currency=")
            p = marketfeeds.StooqProvider(currency, fetch)
        elif provider == "yahoo":
            p = marketfeeds.YahooProvider(fetch)
        elif provider == "factset":
            p = marketfeeds.FactSetProvider(fetch=fetch)
        else:
            raise HTTPException(422, "provider must be yahoo, stooq or factset")
        q = p.quote(symbol.strip())
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except NoData as e:
        raise HTTPException(404, str(e)) from e
    except OSError as e:
        raise HTTPException(502, f"{provider} unreachable: {e}") from e
    return {"symbol": q.symbol, "price": str(q.price), "currency": q.currency, "as_of": q.as_of, "source": q.source}


@app.post("/documents/{doc_id}/vendor-facts")
def vendor_facts(doc_id: str, db: Db, who: Writer, preset: str, commit: bool = False,
                 currency: str | None = None):
    """Propose (or with commit=true store) cited facts from an uploaded PitchBook, Crowdcube or Seedrs/Republic
    CSV export. Each fact quotes its `Header=value` cell and passes the normal gate; rows whose currency
    or date cannot be read come back in `rejected`. Header presets are unverified against real exports."""
    from app.vendorfacts import PRESETS, propose

    doc = _own_doc(db, who, doc_id)
    if preset not in PRESETS:
        raise HTTPException(422, f"preset must be one of {sorted(PRESETS)}")
    if doc.kind != "csv":
        raise HTTPException(422, "vendor-facts reads documents uploaded as CSV exports")
    pages = [(p.number, p.text) for p in sorted(doc.pages, key=lambda p: p.number)]
    props, rejected = propose(pages, preset, currency)
    stored, refused = [], []
    for pr in props:
        item = {"entity": pr.entity, "metric": pr.metric, "period": pr.period, "value": str(pr.value),
                "unit": pr.unit, "page": pr.page, "quote": pr.quote, "row": pr.row}
        if not commit:
            stored.append(item)
            continue
        try:
            f = add_verified_fact(db, tenant_id=who.tenant, entity=pr.entity, metric=pr.metric, period=pr.period,
                                  value=pr.value, unit=pr.unit, document_id=doc_id, page=pr.page, quote=pr.quote,
                                  scale=pr.scale, basis=preset)
            log_event(db, who.tenant, actor(who), "fact.create", {"fact_id": f.id, "entity": pr.entity,
                                                                  "metric": pr.metric, "period": pr.period})
            stored.append({**item, "id": f.id, "status": f.status})
        except CitationError as e:
            db.rollback()
            refused.append({**item, "reason": str(e)})
    return {"committed": commit, "facts": stored, "refused": refused, "rejected": rejected}


@app.get("/uk/company/{number}/accounts")
def uk_accounts(number: str, tenant: Tenant, fetch: Annotated[Callable, Depends(get_ch_fetch)]):
    from dataclasses import asdict

    from app.chfeed import CompanyNotFound, accounts_filings
    try:
        return [asdict(f) for f in accounts_filings(number, fetch)]
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except CompanyNotFound as e:
        raise HTTPException(404, "company not found") from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


def _ch_call(fn, number, fetch):
    from dataclasses import asdict

    from app.chfeed import CompanyNotFound
    try:
        return [asdict(x) for x in fn(number, fetch)]
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except CompanyNotFound as e:
        raise HTTPException(404, "company not found") from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@app.get("/uk/company/{number}/officers")
def uk_officers(number: str, tenant: Tenant, fetch: Annotated[Callable, Depends(get_ch_fetch)]):
    from app import chfeed
    return _ch_call(chfeed.officers, number, fetch)


@app.get("/uk/company/{number}/psc")
def uk_psc(number: str, tenant: Tenant, fetch: Annotated[Callable, Depends(get_ch_fetch)]):
    """People with significant control from the live API (needs COMPANIES_HOUSE_API_KEY). Ceased
    entries are included with ceased_on set; nothing is dropped or defaulted."""
    from app import chfeed
    return _ch_call(chfeed.pscs, number, fetch)


@app.post("/uk/psc/extract")
async def uk_psc_extract(file: Annotated[UploadFile, File()], who: Who, companies: str):
    """Pick the named companies out of an uploaded PSC snapshot (.jsonl, or .zip holding one) and return
    their records with the source line number. `companies` is comma separated. Unreadable lines are
    counted and the first few reported."""
    import io as _io
    import zipfile

    from app.chbulk import iter_psc_snapshot
    from app.chfeed import normalise_number

    try:
        want = {normalise_number(x) for x in companies.split(",") if x.strip()}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not want or len(want) > 500:
        raise HTTPException(422, "give between 1 and 500 company numbers")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    if data[:2] == b"PK":
        try:
            z = zipfile.ZipFile(_io.BytesIO(data))
            names = [n for n in z.namelist() if n.lower().endswith((".jsonl", ".txt", ".json"))]
            if not names:
                raise HTTPException(422, "no .jsonl file in the zip")
            lines = z.open(names[0])
        except zipfile.BadZipFile as e:
            raise HTTPException(422, "corrupt zip") from e
    else:
        lines = _io.BytesIO(data)
    found, errors = [], []
    from dataclasses import asdict
    for rec in iter_psc_snapshot(lines, want):
        if isinstance(rec, dict):
            errors.append(rec)
        else:
            found.append(asdict(rec))
    missing = sorted(want - {r["company_number"] for r in found})
    return {"records": found, "not_in_file": missing, "unreadable_lines": len(errors), "unreadable_sample": errors[:5]}


@app.get("/email-links")
def email_links(db: Db, who: Who):
    """Emails this key can see, matched to deals by company name or website domain, each with its source link."""
    return {"links": links_for(db, who)}


@app.get("/facts.xlsx")
def facts_xlsx(db: Db, who: Who, entity: str | None = None):
    """Verified and reviewed facts as a workbook; each value cell's comment lists its sources."""
    log_event(db, who.tenant, actor(who), "facts.export", {"entity": entity, "format": "xlsx"})
    return Response(build_facts_xlsx(db, who.tenant, entity, visible_doc_ids(db, who)), headers={
        "Content-Disposition": 'attachment; filename="facts.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/memo.docx")
def memo_docx(entity: str, db: Db, who: Who):
    log_event(db, who.tenant, actor(who), "memo.export", {"entity": entity, "format": "docx"})
    return Response(build_memo_docx(db, who.tenant, entity, visible_doc_ids(db, who)), headers={
        "Content-Disposition": 'attachment; filename="memo.docx"'},
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/memo.pptx")
def memo_pptx(entity: str, db: Db, who: Who):
    log_event(db, who.tenant, actor(who), "memo.export", {"entity": entity, "format": "pptx"})
    return Response(build_memo_pptx(db, who.tenant, entity, visible_doc_ids(db, who)), headers={
        "Content-Disposition": 'attachment; filename="memo.pptx"'},
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.get("/search")
def search(q: str, db: Db, who: Who, doc_id: str | None = None, k: int = 5):
    if doc_id:
        _own_doc(db, who, doc_id)
    query = (db.query(PageRow).join(Document, Document.id == PageRow.document_id)
             .filter(Document.tenant_id == who.tenant))  # tenant + deal filter BEFORE ranking
    scope = visible_doc_ids(db, who)
    if scope is not None:
        query = query.filter(PageRow.document_id.in_(scope))
    if doc_id:
        query = query.filter(PageRow.document_id == doc_id)
    rows = query.all()
    index = default_index([(r.document_id, r.number, r.text) for r in rows])
    text = {(r.document_id, r.number): r.text for r in rows}
    return [{"document_id": h.doc_id, "page": h.page, "score": round(h.score, 3),
             "snippet": text[(h.doc_id, h.page)][:300]}
            for h in index.search(q, k=k, doc_ids={doc_id} if doc_id else None)]


class CompanyIn(BaseModel):
    name: str
    sector: str | None = None
    ownership_pct: Decimal | None = None


@app.get("/portfolio/companies/{company_id}/add-ons")
def company_add_ons(company_id: int, db: Db, who: Who):
    """Targets in this company's sector, minus companies already owned, screened against the firm rule."""
    try:
        return add_on.add_on_candidates(db, who.tenant, company_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/portfolio/companies", status_code=201)
def create_company(body: CompanyIn, db: Db, who: Writer):
    tenant = who.tenant
    c = PortfolioCompany(tenant_id=tenant, **body.model_dump())
    db.add(c)
    db.commit()
    log_event(db, tenant, actor(who), "company.create", {"company_id": c.id, "name": c.name})
    return {"id": c.id, "name": c.name}


@app.post("/portfolio/companies/{company_id}/observations", status_code=201)
def add_observation(company_id: int, fact_id: int, db: Db, who: Writer):
    tenant = who.tenant
    f = db.get(Fact, fact_id)
    if f is not None and f.tenant_id == tenant and not fact_visible(f, visible_doc_ids(db, who)):
        raise HTTPException(422, "observation requires a verified, cited fact")
    try:
        o = record_observation(db, tenant, company_id, fact_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, tenant, actor(who), "kpi.record", {"observation_id": o.id, "fact_id": fact_id})
    return {"id": o.id, "metric": o.metric, "period": o.period, "value": str(o.value)}


@app.get("/portfolio/companies/{company_id}/kpis")
def kpis(company_id: int, db: Db, who: Who):
    scope = visible_doc_ids(db, who)
    return [{"metric": o.metric, "period": o.period, "value": str(o.value), "unit": o.unit,
             "fact_id": o.fact_id} for o in current_kpis(db, who.tenant, company_id)
            if fact_visible(db.get(Fact, o.fact_id), scope)]


class CovenantIn(BaseModel):
    kpi_metric: str
    operator: str
    threshold_fact_id: int


@app.post("/portfolio/companies/{company_id}/covenants", status_code=201)
def create_covenant(company_id: int, body: CovenantIn, db: Db, who: Writer):
    f = db.get(Fact, body.threshold_fact_id)
    if f is not None and f.tenant_id == who.tenant and not fact_visible(f, visible_doc_ids(db, who)):
        raise HTTPException(422, "covenant threshold must be a verified, cited fact")
    try:
        cov = add_covenant(db, who.tenant, company_id, body.kpi_metric, body.operator, body.threshold_fact_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "covenant.create", {"covenant_id": cov.id, "company_id": company_id})
    return {"id": cov.id}


@app.get("/portfolio/companies/{company_id}/covenants")
def covenant_status(company_id: int, db: Db, who: Who):
    """Every covenant of the company with its tests; `breaches` lists the alerts."""
    scope = visible_doc_ids(db, who)
    covs = db.query(Covenant).filter_by(tenant_id=who.tenant, company_id=company_id).all()
    out = [{"id": c.id, "kpi_metric": c.kpi_metric, "operator": c.operator,
            "tests": evaluate_covenant(db, c, scope)} for c in covs]
    breaches = [{"covenant_id": c["id"], "kpi_metric": c["kpi_metric"], **t}
                for c in out for t in c["tests"] if t["status"] in ("breach", "unit_mismatch")]
    return {"covenants": out, "breaches": breaches}


class TieOutIn(BaseModel):
    rows: dict[str, list[Decimal | None]]  # null = a dash printed in the table
    base: list[Decimal]
    total: list[Decimal]


@app.post("/calc/tieout")
def calc_tieout(body: TieOutIn, who: Who):
    """Place short table rows into columns using the printed column totals. Never guesses."""
    r = tie_out(body.rows, body.base, body.total)
    return {"status": r.status, "solutions": r.solutions, "detail": r.detail,
            "rows": None if r.rows is None else {k: [str(x) for x in v] for k, v in r.rows.items()}}


class SumCheckIn(BaseModel):
    parts: list[Decimal]
    stated: Decimal
    rounding_unit: Decimal = Decimal(0)


@app.post("/calc/sumcheck")
def calc_sumcheck(body: SumCheckIn, who: Who):
    r = sum_check(body.parts, body.stated, body.rounding_unit)
    return {"status": r.status, "computed": str(r.computed), "stated": str(r.stated),
            "difference": str(r.difference), "detail": r.detail}


@app.post("/holdings/import", status_code=201)
async def holdings_import(file: Annotated[UploadFile, File()], db: Db, who: Writer,
                          platform: Annotated[str, Form()],
                          currency: Annotated[str | None, Form()] = None,
                          mapping: Annotated[str | None, Form()] = None):
    """Import a holdings export the user downloaded. `mapping` is JSON like {"company": "Business"}."""
    import json as _json

    if who.deals is not None:
        raise HTTPException(403, "walled keys cannot import holdings")
    platform = platform.strip()
    if not platform:
        raise HTTPException(422, "platform label required")
    try:
        mp = _json.loads(mapping) if mapping else None
        if mp is not None and not (isinstance(mp, dict) and all(isinstance(v, str) for v in mp.values())):
            raise ValueError
    except ValueError as e:
        raise HTTPException(422, "mapping must be a JSON object of field to column name") from e
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(422, "file must be UTF-8 text") from e
    rows, errors, missing = parse_holdings(text, mp, currency)
    if missing:
        raise HTTPException(422, f"no column found for: {missing}; send a mapping")
    if not rows:
        raise HTTPException(422, {"detail": "no valid rows", "errors": errors[:50]})
    res = ingest_any(db, who.tenant, data, file.filename or "holdings.csv")
    if not res.documents:
        reason = res.skipped[0]["reason"] if res.skipped else "cannot store file"
        raise HTTPException(409 if "already stored" in reason else 422, reason)
    doc = res.documents[0]
    if db.query(Holding).filter_by(tenant_id=who.tenant, document_id=doc.id).first():
        raise HTTPException(409, "this file was already imported")
    for r in rows:
        db.add(Holding(tenant_id=who.tenant, platform=platform, company=r.company, shares=r.shares,
                       price=r.price, currency=r.currency, acquired=r.acquired, document_id=doc.id, line=r.line))
    db.commit()
    log_event(db, who.tenant, actor(who), "holdings.import",
              {"document_id": doc.id, "platform": platform, "imported": len(rows), "rejected": len(errors)})
    return {"document_id": doc.id, "imported": len(rows), "rejected": len(errors), "errors": errors[:50]}


@app.get("/holdings")
def holdings_list(db: Db, who: Who, platform: str | None = None):
    if who.deals is not None:
        return []
    q = db.query(Holding).filter_by(tenant_id=who.tenant)
    if platform:
        q = q.filter_by(platform=platform)
    return [{"id": h.id, "platform": h.platform, "company": h.company, "shares": str(h.shares),
             "price": str(h.price), "currency": h.currency, "cost": str(h.shares * h.price),
             "acquired": h.acquired, "document_id": h.document_id, "line": h.line}
            for h in q.order_by(Holding.id)]


class LedgerEventIn(BaseModel):
    kind: str
    date: str
    source: str
    allotted: Decimal | None = None
    total_after: Decimal | None = None
    old_total: Decimal | None = None


class LedgerIn(BaseModel):
    opening: Decimal
    opening_source: str
    events: list[LedgerEventIn]


@app.post("/calc/share-ledger")
def calc_share_ledger(body: LedgerIn, who: Who):
    """Reconcile issued share totals across SH01/SH02/SH19 events. Unreconciled forms are listed, never forced."""
    if any(e.kind not in ("allot", "statement", "consolidate") for e in body.events) or len(body.events) > 500:
        raise HTTPException(422, "kind must be allot, statement or consolidate; at most 500 events")
    try:
        led = reconcile_shares(body.opening, body.opening_source, [LedgerEvent(**e.model_dump()) for e in body.events])
    except ValueError as e:
        raise HTTPException(422, f"bad date: {e}") from e
    return {"running": str(led.running), "problems": led.problems,
            "entries": [{"source": x.source, "date": x.date, "kind": x.kind, "status": x.status,
                         "running_after": str(x.running_after), "detail": x.detail} for x in led.entries]}


class FlowIn(BaseModel):
    date: DateT
    amount: Decimal


class FundIn(BaseModel):
    flows: list[FlowIn]
    nav: Decimal
    as_of: DateT


@app.post("/calc/fund-metrics")
def calc_fund_metrics(body: FundIn, who: Who):
    """DPI, RVPI, TVPI and XIRR from dated flows (paid in negative, distributions positive) and a NAV."""
    if len(body.flows) > 5000:
        raise HTTPException(422, "at most 5000 flows")
    try:
        m = fund_metrics([(f.date, f.amount) for f in body.flows], body.nav, body.as_of)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    q = lambda v: None if v is None else str(v.quantize(Decimal("0.0001")))
    return {"paid_in": str(m.paid_in), "distributed": str(m.distributed), "nav": str(m.nav),
            "dpi": q(m.dpi), "rvpi": q(m.rvpi), "tvpi": q(m.tvpi),
            "irr": None if m.irr is None else round(m.irr, 6), "irr_note": m.irr_note}


class EvalIn(BaseModel):
    suite: str
    metrics: dict
    note: str | None = None


@app.post("/evals", status_code=201)
def eval_record(body: EvalIn, db: Db, who: Writer):
    import json as _json

    suite = body.suite.strip()
    if not suite or len(suite) > 64:
        raise HTTPException(422, "suite name required (64 characters at most)")
    text = _json.dumps(body.metrics, default=str)
    if len(text) > 200_000:
        raise HTTPException(413, "metrics too large")
    r = EvalRun(tenant_id=who.tenant, suite=suite, metrics=text, note=body.note, ran_at=_now_iso(),
                recorded_by=actor(who))
    db.add(r)
    db.commit()
    log_event(db, who.tenant, actor(who), "eval.record", {"suite": suite, "id": r.id})
    return {"id": r.id}


@app.get("/evals")
def eval_list(db: Db, who: Who, suite: str | None = None, limit: int = 100):
    import json as _json

    q = db.query(EvalRun).filter_by(tenant_id=who.tenant)
    if suite:
        q = q.filter_by(suite=suite)
    rows = q.order_by(EvalRun.id.desc()).limit(max(1, min(limit, 500))).all()
    return [{"id": r.id, "suite": r.suite, "ran_at": r.ran_at, "note": r.note, "recorded_by": r.recorded_by,
             "metrics": _json.loads(r.metrics)} for r in rows]


class PrefClassIn(BaseModel):
    name: str
    shares: Decimal
    invested: Decimal
    pref_multiple: Decimal = Decimal(1)
    rank: int = 1
    participating: bool = False
    cap_multiple: Decimal | None = None


class WaterfallIn(BaseModel):
    exit_value: Decimal
    common_shares: Decimal
    classes: list[PrefClassIn]


@app.post("/calc/waterfall")
def calc_waterfall(body: WaterfallIn, who: Who):
    """Exit proceeds by class for the stated terms. Terms the model does not cover are not applied."""
    if len(body.classes) > 50:
        raise HTTPException(422, "at most 50 classes")
    try:
        r = waterfall(body.exit_value, [PrefClass(**c.model_dump()) for c in body.classes], body.common_shares)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"status": r.status, "detail": r.detail, "converted": r.converted,
            "payouts": {k: str(v) for k, v in r.payouts.items()}}


class CompsIn(BaseModel):
    target: str
    peers: list[str]
    period: str
    metrics: list[str] = ["revenue", "ebitda"]
    target_period: str | None = None
    ev_period: str | None = None


@app.post("/calc/comps")
def calc_comps(body: CompsIn, db: Db, who: Who):
    """Trading comps (or precedents: peers are deal entities with enterprise_value facts) and implied range."""
    if len(body.peers) > 200 or len(body.metrics) > 10:
        raise HTTPException(422, "too many peers or metrics")
    return comps_mod.run(db, who.tenant, body.target, body.peers, body.period, body.metrics,
                         visible_doc_ids(db, who), body.target_period, body.ev_period)


@app.post("/calc/comps.docx")
def calc_comps_docx(body: CompsIn, db: Db, who: Who):
    """Word note of the comps result with a source for every input."""
    res = comps_mod.run(db, who.tenant, body.target, body.peers, body.period, body.metrics,
                        visible_doc_ids(db, who), body.target_period, body.ev_period)
    log_event(db, who.tenant, actor(who), "comps.export", {"format": "docx", "target": body.target})
    return Response(comps_mod.to_docx(db, res), headers={"Content-Disposition": 'attachment; filename="comps.docx"'},
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/calc/comps.pptx")
def calc_comps_pptx(body: CompsIn, db: Db, who: Who):
    """Slide deck of the comps result; every figure cites its source line."""
    res = comps_mod.run(db, who.tenant, body.target, body.peers, body.period, body.metrics,
                        visible_doc_ids(db, who), body.target_period, body.ev_period)
    log_event(db, who.tenant, actor(who), "comps.export", {"format": "pptx", "target": body.target})
    return Response(comps_mod.to_pptx(db, res), headers={"Content-Disposition": 'attachment; filename="comps.pptx"'},
                    media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.get("/documents/{doc_id}/legal-terms")
def legal_terms(doc_id: str, doc_type: str, db: Db, who: Who):
    """Key terms (governing law, term, caps, covenants...) as cited sentences. doc_type: nda | spa | credit."""
    _own_doc(db, who, doc_id)
    pages = [(p.number, p.text) for p in db.query(PageRow).filter_by(document_id=doc_id).order_by(PageRow.number)]
    try:
        out = legal_mod.extract(pages, doc_type)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    for f in out["findings"]:
        f["document_id"] = doc_id
    out["red_flags"] = legal_mod.red_flags(out)
    return out


@app.get("/precedents/summary")
def precedents_summary(db: Db, who: Who, document_ids: str):
    """Stated EV and multiples across deal documents (comma-separated ids), with page and quote per input."""
    ids = [x for x in document_ids.split(",") if x][:200]
    if not ids:
        raise HTTPException(422, "document_ids required")
    deals = []
    for doc_id in ids:
        _own_doc(db, who, doc_id)
        pages = [(p.number, p.text) for p in db.query(PageRow).filter_by(document_id=doc_id).order_by(PageRow.number)]
        deals.append({"name": doc_id, "document_id": doc_id, "terms": prec_mod.extract(pages)})
    return {"deals": deals, "stats": prec_mod.summarise(deals)}


@app.get("/precedents/scan")
def precedents_scan(who: Who, since: str, until: str, limit: int = 25, form: str = "8-K", theme: str | None = None):
    """Merger 8-Ks filed in a date range, each read from its filing with stated EV and multiples cited to the URL.
    theme=vertical_saas_take_private keeps only deals whose filing names a sponsor buyer and a software target."""
    if not 1 <= limit <= 100:
        raise HTTPException(422, "limit must be 1 to 100")
    try:
        return pfetch_mod.build(since, until, limit=limit, form=form, theme=theme)
    except RuntimeError as e:  # SEC_USER_AGENT not set
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/documents/{doc_id}/covenant-tests")
def covenant_tests(doc_id: str, db: Db, who: Who):
    """Financial covenant tests in a credit agreement, each with its section, page and quote."""
    _own_doc(db, who, doc_id)
    pages = [(p.number, p.text) for p in db.query(PageRow).filter_by(document_id=doc_id).order_by(PageRow.number)]
    return {"document_id": doc_id, "tests": covparse_mod.extract(pages)}


class WorkflowIn(BaseModel):
    name: str
    kind: str
    every_days: int
    params: dict = {}
    recipients: list[str] = []


def _wf_out(w) -> dict:
    return {"id": w.id, "name": w.name, "kind": w.kind, "every_days": w.every_days, "next_run": w.next_run,
            "last_run": w.last_run, "last_status": w.last_status, "active": bool(w.active)}


@app.post("/workflows", status_code=201)
def workflow_create(body: WorkflowIn, db: Db, who: Writer):
    if body.kind == "alert_digest" and who.restricted:
        raise HTTPException(403, "alert digests cover the whole tenant; use an unrestricted key")
    try:
        w = wf_mod.create(db, who.tenant, body.name, body.kind, body.every_days, body.params, body.recipients)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "workflow.create", {"id": w.id, "kind": w.kind})
    return _wf_out(w)


@app.get("/workflows")
def workflow_list(db: Db, who: Who):
    return [_wf_out(w) for w in db.query(WorkflowSchedule).filter_by(tenant_id=who.tenant).order_by(WorkflowSchedule.id)]


@app.get("/workflows/{wid}/last")
def workflow_last(wid: int, db: Db, who: Who):
    w = db.get(WorkflowSchedule, wid)
    if w is None or w.tenant_id != who.tenant:
        raise HTTPException(404, "workflow not found")
    return {**_wf_out(w), "last_result": w.last_result}


@app.delete("/workflows/{wid}")
def workflow_delete(wid: int, db: Db, who: Writer):
    w = db.get(WorkflowSchedule, wid)
    if w is None or w.tenant_id != who.tenant:
        raise HTTPException(404, "workflow not found")
    w.active = 0
    db.commit()
    log_event(db, who.tenant, actor(who), "workflow.delete", {"id": wid})
    return {"id": wid, "active": False}


@app.post("/workflows/run-due")
def workflow_run_due(db: Db, who: Writer):
    """Run every due schedule of this tenant now. Call from cron; emails when SMTP_HOST is set."""
    runs = wf_mod.run_due(db, who.tenant, visible_doc_ids(db, who), wf_mod.smtp_mailer(), chat=chat_poster())
    log_event(db, who.tenant, actor(who), "workflow.run_due", {"ran": len(runs)})
    return runs


class TargetBody(BaseModel):
    name: str
    source: str = "manual"
    source_ref: str
    source_url: str | None = None
    sector: str | None = None
    sic: str | None = None
    country: str | None = None
    region: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    revenue: Decimal | None = None
    currency: str | None = None
    revenue_period: str | None = None
    revenue_url: str | None = None


class SecImport(BaseModel):
    submissions: dict
    companyfacts: dict | None = None


class ChImport(BaseModel):
    csv_text: str


class ChNumbersImport(BaseModel):
    numbers: list[str] = Field(min_length=1, max_length=200)


SCREEN_PROFILE_KEYS = ("deal_screening_criteria", "target_ev_range", "target_ebitda_range")


class Screen(BaseModel):
    sectors: list[str] = []
    countries: list[str] = []
    min_revenue: Decimal | None = None
    max_revenue: Decimal | None = None
    limit: int = 200


@app.post("/targets", status_code=201)
def targets_add(body: list[TargetBody], db: Db, who: Writer):
    if not 0 < len(body) <= 500:
        raise HTTPException(422, "send 1 to 500 targets")
    if any(t.revenue is not None and not (t.revenue_url or t.source_url) for t in body):
        raise HTTPException(422, "revenue needs a revenue_url or source_url")
    new, upd = tg_mod.upsert(db, who.tenant, [tg_mod.TargetIn(**t.model_dump()) for t in body])
    log_event(db, who.tenant, actor(who), "target.upsert", {"new": new, "updated": upd})
    return {"new": new, "updated": upd}


@app.post("/targets/import/sec", status_code=201)
def targets_import_sec(body: SecImport, db: Db, who: Writer):
    try:
        t = tg_mod.sec_target(body.submissions, body.companyfacts)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"not a SEC submissions document: {e}") from e
    new, upd = tg_mod.upsert(db, who.tenant, [t])
    return {"new": new, "updated": upd, "revenue_found": t.revenue is not None}


@app.post("/targets/import/companies-house", status_code=201)
def targets_import_ch(body: ChImport, db: Db, who: Writer):
    items = tg_mod.ch_targets(body.csv_text)[:5000]
    new, upd = tg_mod.upsert(db, who.tenant, items)
    return {"new": new, "updated": upd}


@app.post("/targets/import/companies-house/numbers", status_code=201)
def targets_import_ch_numbers(body: ChNumbersImport, db: Db, who: Writer):
    """Live lookup per number: CH_API_KEY when set, else the keyless public page. Each row keeps its
    source link, so a target can always be traced back to the Companies House page it came from."""
    items, skipped = ch_mod.company_numbers_to_targets(body.numbers)
    new, upd = tg_mod.upsert(db, who.tenant, items)
    return {"new": new, "updated": upd, "skipped": skipped}


def _target_query(db, tenant, sector, country, min_revenue, max_revenue, q, status):
    qs = db.query(Target).filter(Target.tenant_id == tenant)
    if sector:
        qs = qs.filter(Target.sector.ilike(f"%{sector}%"))
    if country:
        qs = qs.filter(Target.country == country)
    if min_revenue is not None:
        qs = qs.filter(Target.revenue >= min_revenue)
    if max_revenue is not None:
        qs = qs.filter(Target.revenue <= max_revenue)
    if q:
        qs = qs.filter(Target.name.ilike(f"%{q}%"))
    if status:
        qs = qs.filter(Target.status == status)
    return qs


@app.get("/targets")
def targets_list(db: Db, who: Who, sector: str | None = None, country: str | None = None,
                 min_revenue: Decimal | None = None, max_revenue: Decimal | None = None,
                 q: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0):
    """Filterable target list for the map and table. Revenue filters exclude targets with unknown revenue."""
    qs = _target_query(db, who.tenant, sector, country, min_revenue, max_revenue, q, status)
    total = qs.count()
    rows = qs.order_by(Target.id).offset(max(offset, 0)).limit(min(max(limit, 1), 1000)).all()
    return {"total": total, "items": [tg_mod.to_dict(t) for t in rows]}


@app.get("/targets/facets")
def targets_facets(db: Db, who: Who):
    """Counts for the filter panel and map: by sector, country, status, plus how many have no revenue."""
    from sqlalchemy import func
    out = {}
    for name, col in (("sector", Target.sector), ("country", Target.country), ("status", Target.status)):
        rows = (db.query(col, func.count()).filter(Target.tenant_id == who.tenant).group_by(col)
                .order_by(func.count().desc()).all())
        out[name] = [{"value": v, "count": n} for v, n in rows]
    out["total"] = db.query(Target).filter_by(tenant_id=who.tenant).count()
    out["revenue_unknown"] = db.query(Target).filter(Target.tenant_id == who.tenant, Target.revenue.is_(None)).count()
    return out


class OutreachSend(BaseModel):
    target_id: int
    to: list[str] = Field(min_length=1, max_length=20)
    sender: str = Field(min_length=1, max_length=120)
    firm: str = Field(min_length=1, max_length=120)
    memo_entity: str | None = Field(default=None, max_length=200)  # also attach the IC memo deck for this entity
    confirm_subject: str = Field(min_length=1, max_length=300)  # the exact subject of the draft the sender reviewed


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


OUTREACH_SENDERS = ("admin", "partner", "vp")


@app.post("/targets/outreach/send", status_code=200)
def targets_outreach_send(body: OutreachSend, db: Db, who: Writer):
    """Email one target's outreach draft with its cited research note (.docx) attached.

    Only a senior person's key may send, and only for the draft they reviewed: `confirm_subject` must equal
    the subject of the draft as built now. Agents, workflows and schedules never reach this route; the agent
    tools and the workflow kinds do not include it (see tests/test_outreach_guard.py)."""
    if who.role not in OUTREACH_SENDERS or who.restricted:
        raise HTTPException(403, "sending outreach needs a senior, unrestricted person's key")
    t = db.get(Target, body.target_id)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    try:
        to = notify_mod.valid_recipients(body.to)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    msg = outreach_mod.draft(t, body.sender, body.firm)
    if body.confirm_subject != msg["subject"]:
        raise HTTPException(409, "the draft changed since it was reviewed; review it again and confirm its subject")
    scope = None if who.deals is None else set(who.deals)
    name = f"research-{t.id}.docx"
    files = [(name, research_mod.build_docx(db, who.tenant, t, scope), DOCX_MIME)]
    if body.memo_entity:
        files.append(("memo.pptx", build_memo_pptx(db, who.tenant, body.memo_entity, visible_doc_ids(db, who)), PPTX_MIME))
    try:
        notify_mod.send_email(to, msg["subject"], msg["body"], files)
    except notify_mod.MailNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except OSError as e:  # SMTP host unreachable or refused: a gateway failure, not a server bug
        raise HTTPException(502, f"mail server unreachable: {e}") from e
    log_event(db, who.tenant, actor(who), "target.outreach_sent", {"id": t.id, "to": len(to)})
    return {"sent": len(to), "attached": [f[0] for f in files]}


@app.get("/targets/{tid}/research.docx")
def target_research(tid: int, db: Db, who: Who):
    """Research note for one target: identity, revenue with filing link, sector benchmark, prior mentions, sources."""
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    log_event(db, who.tenant, actor(who), "target.research_export", {"id": tid})
    return Response(research_mod.build_docx(db, who.tenant, t, None if who.deals is None else set(who.deals)),
                    headers={"Content-Disposition": f'attachment; filename="research-{tid}.docx"'},
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/seen-before")
def seen_before(q: str, db: Db, who: Who):
    """Have we seen this company or deal before? Searches targets, portfolio companies and deals you can see."""
    if len(q.strip()) < 2:
        raise HTTPException(422, "query must be at least 2 characters")
    return seen_mod.lookup(db, who.tenant, q, None if who.deals is None else set(who.deals))


@app.get("/targets/benchmark")
def targets_benchmark(db: Db, who: Who, sector: str | None = None, target_id: int | None = None):
    """Revenue median and quartiles for a sector, and where one target sits. Excludes targets with no revenue."""
    t = None
    if target_id is not None:
        t = db.get(Target, target_id)
        if t is None or t.tenant_id != who.tenant:
            raise HTTPException(404, "target not found")
    return tg_mod.benchmark(db, who.tenant, sector, t)


@app.post("/targets/screen")
def targets_screen(body: Screen, db: Db, who: Who):
    """Apply strategy criteria. verdict: match | review (some criterion unknown) | fail. Failures are omitted."""
    source = None
    if body.sectors or body.countries or body.min_revenue is not None or body.max_revenue is not None:
        c = tg_mod.Criteria(body.sectors, body.countries, body.min_revenue, body.max_revenue)
    else:  # no criteria in the request: use the accepted firm screening rule, cited
        rule, c = al.profile_criteria(db, who.tenant)
        if rule is None:
            raise HTTPException(422, "give criteria, or accept a firm deal_screening_criteria rule first")
        source = {"key": rule.key, "value": rule.value, "document_id": rule.document_id, "page": rule.page,
                  "quote": rule.quote}
    out = []
    for t in db.query(Target).filter_by(tenant_id=who.tenant).order_by(Target.id).all():
        e = tg_mod.evaluate(t, c)
        if e["verdict"] != "fail":
            d = tg_mod.to_dict(t)
            sources = [{"label": lbl, "url": u} for lbl, u in
                       (("company record", d["source_url"]), ("revenue", d["revenue_url"])) if u]
            out.append({**d, **e, "sources": sources})
    out.sort(key=lambda r: r["verdict"] != "match")
    profile = [fk.row_dict(r) for r in (fk.newest_accepted(db, who.tenant, k)
                                        for k in SCREEN_PROFILE_KEYS) if r is not None]
    return {"matches": sum(r["verdict"] == "match" for r in out), "review": sum(r["verdict"] == "review" for r in out),
            "criteria_profile": profile, "criteria_source": source,
            "applied": {"sectors": c.sectors, "countries": c.countries,
                        "min_revenue": None if c.min_revenue is None else str(c.min_revenue),
                        "max_revenue": None if c.max_revenue is None else str(c.max_revenue)},
            "items": out[:min(max(body.limit, 1), 1000)]}


class OutreachIn(BaseModel):
    target_ids: list[int]
    sender: str
    firm: str
    thesis: str | None = None


@app.post("/targets/outreach")
def targets_outreach(body: OutreachIn, db: Db, who: Writer):
    """Mail-merge drafts for chosen targets. Nothing is sent; revenue is quoted only with its filing link."""
    if not 0 < len(body.target_ids) <= 200:
        raise HTTPException(422, "send 1 to 200 target ids")
    rows = db.query(Target).filter(Target.tenant_id == who.tenant, Target.id.in_(body.target_ids)).all()
    missing = sorted(set(body.target_ids) - {t.id for t in rows})
    if missing:
        raise HTTPException(404, f"targets not found: {missing}")
    log_event(db, who.tenant, actor(who), "target.outreach_draft", {"count": len(rows)})
    return [outreach_mod.draft(t, body.sender, body.firm, body.thesis) for t in rows]


class TargetStatus(BaseModel):
    status: str
    notes: str | None = None


class EnrichBody(BaseModel):
    url: str


@app.post("/targets/{tid}/enrich/website")
def targets_enrich_website(tid: int, body: EnrichBody, db: Db, who: Writer):
    """Reads the company's own homepage (https only) and stores its title and description with the URL."""
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    try:
        fields = enrich.enrich_website(db, who.tenant, t, body.url, CONNECTOR_HTTP)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except OSError as e:
        raise HTTPException(502, f"could not fetch the homepage: {e}") from e
    log_event(db, who.tenant, actor(who), "target.enrich_website", {"id": tid, "website": t.website})
    return dict(tg_mod.to_dict(t), fetched=fields)


@app.patch("/targets/{tid}")
def targets_update(tid: int, body: TargetStatus, db: Db, who: Writer):
    if body.status not in ("new", "screened", "contacted", "passed"):
        raise HTTPException(422, "status must be new, screened, contacted or passed")
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    t.status, t.notes = body.status, body.notes if body.notes is not None else t.notes
    db.commit()
    log_event(db, who.tenant, actor(who), "target.status", {"id": tid, "status": body.status})
    return tg_mod.to_dict(t)


@app.get("/portfolio/report")
def portfolio_report(db: Db, who: Who):
    return build_report(db, who.tenant, visible_doc_ids(db, who))


@app.get("/portfolio/report.docx")
def portfolio_report_docx(db: Db, who: Who):
    log_event(db, who.tenant, actor(who), "report.export", {"format": "docx"})
    return Response(build_report_docx(db, who.tenant, visible_doc_ids(db, who)), headers={
        "Content-Disposition": 'attachment; filename="portfolio-report.docx"'},
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


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


class ExtractIn(BaseModel):
    schema_name: str
    entity: str
    period: str


@app.get("/extract/schemas")
def extract_schemas(tenant: Tenant):
    return {k: [{"metric": f.metric, "unit": f.unit, "description": f.description} for f in v]
            for k, v in SCHEMAS.items()}


@app.post("/documents/{doc_id}/extract")
def extract(doc_id: str, body: ExtractIn, db: Db, who: Writer, llm: Annotated[LLM, Depends(llm_dependency)]):
    doc = _own_doc(db, who, doc_id)
    if body.schema_name not in SCHEMAS:
        raise HTTPException(422, f"schema must be one of {sorted(SCHEMAS)}")
    res = extract_schema(db, who.tenant, llm, doc, body.schema_name, body.entity, body.period)
    log_event(db, who.tenant, actor(who), "extract",
              {"document_id": doc.id, "schema": body.schema_name,
               "accepted": sum(r.status == "accepted" for r in res.results)})
    return {"schema": res.schema, "detail": res.detail,
            "note": "accepted values are stored as status 'auto'; accept them in the review queue to use them",
            "fields": [{"metric": r.metric, "status": r.status, "value": None if r.value is None else str(r.value),
                        "page": r.page, "quote": r.quote, "reason": r.reason, "fact_id": r.fact_id}
                       for r in res.results]}


class DDQIn(BaseModel):
    questions: list[str]


@app.post("/ddq")
def ddq(body: DDQIn, db: Db, who: Who, llm: Annotated[LLM, Depends(llm_dependency)]):
    """Answer a questionnaire. Each question is answered on its own with cited claims only.
    Anything not answered (abstained, failed, empty) is flagged for a human; nothing is filled in."""
    qs = [q.strip() for q in body.questions]
    if not qs or len(qs) > 200:
        raise HTTPException(422, "send 1 to 200 questions")
    scope = visible_doc_ids(db, who)
    items = []
    for i, q in enumerate(qs, 1):
        if not q:
            items.append({"n": i, "question": q, "status": "skipped", "detail": "empty question",
                          "claims": [], "needs_human": True})
            continue
        try:
            a = answer_question(db, who.tenant, llm, q, None, scope=scope)
        except Exception as e:  # noqa: BLE001 - one bad question must not sink the batch
            items.append({"n": i, "question": q, "status": "error", "detail": type(e).__name__,
                          "claims": [], "needs_human": True})
            continue
        items.append({"n": i, "question": q, "status": a.status, "detail": a.detail,
                      "claims": [{"text": c.text, "document_id": c.doc_id, "page": c.page, "quote": c.quote}
                                 for c in a.claims],
                      "needs_human": a.status != "answered" or not a.claims})
    log_event(db, who.tenant, actor(who), "ddq", {"questions": len(qs),
                                                   "needs_human": sum(x["needs_human"] for x in items)})
    return {"items": items, "needs_human": sum(x["needs_human"] for x in items), "total": len(items)}


@app.post("/ask")
def ask(body: AskIn, db: Db, who: Who, llm: Annotated[LLM, Depends(llm_dependency)]):
    tenant = who.tenant
    if body.doc_id:
        _own_doc(db, who, body.doc_id)
    a = answer_question(db, tenant, llm, body.question, body.doc_id, scope=visible_doc_ids(db, who))
    log_event(db, tenant, actor(who), "ask", {"question": body.question, "status": a.status,
                                         "claims": len(a.claims), "rejected": len(a.rejected)})
    cite = lambda c: {"text": c.text, "document_id": c.doc_id, "page": c.page, "quote": c.quote}
    return {"status": a.status, "detail": a.detail, "claims": [cite(c) for c in a.claims],
            "rejected": [{**cite(c), "reason": c.reason} for c in a.rejected]}


class FKExtractIn(BaseModel):
    document_id: str
    keys: list[str] | None = None


class FKReviewIn(BaseModel):
    status: str
    value: str | None = None


@app.get("/firm-knowledge/terms")
def fk_terms(who: Who):
    return [{"key": t.key, "group": t.group, "label": t.label, "hint": t.hint} for t in fk.TERMS]


@app.get("/firm-knowledge")
def fk_profile(db: Db, who: Who, include_pending: bool = False):
    return {"profile": fk.profile(db, who.tenant, include_pending), "coverage": fk.coverage(db, who.tenant)}


@app.post("/firm-knowledge/extract")
def fk_extract(body: FKExtractIn, db: Db, who: Writer, llm: Annotated[LLM, Depends(llm_dependency)]):
    doc = _own_doc(db, who, body.document_id)
    bad = [k for k in body.keys or [] if k not in fk.BY_KEY]
    if bad:
        raise HTTPException(422, f"unknown keys: {bad}")
    res = fk.extract_profile(db, who.tenant, llm, doc, body.keys)
    log_event(db, who.tenant, actor(who), "firm_knowledge.extract",
              {"document_id": doc.id, "saved": len(res.saved), "rejected": len(res.rejected)})
    return {"saved": [fk.row_dict(r) for r in res.saved], "rejected": res.rejected, "detail": res.detail}


@app.post("/firm-knowledge/{fk_id}/review")
def fk_review(fk_id: int, body: FKReviewIn, db: Db, who: Writer):
    try:
        r = fk.review(db, who.tenant, fk_id, body.status, body.value)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if r is None:
        raise HTTPException(404, "not found")
    log_event(db, who.tenant, actor(who), "firm_knowledge.review", {"id": fk_id, "status": r.status})
    return fk.row_dict(r)


class AgentIn(BaseModel):
    goal: str
    max_steps: int = 6


class WorkflowIn(BaseModel):
    inputs: dict = {}


@app.get("/agent/tools")
def agent_tools(who: Who):
    return [{"name": t.name, "description": t.description, "params": t.params, "writes": t.writes}
            for t in ag.TOOLS.values()]


@app.get("/agent/workflows")
def agent_workflows(who: Who):
    return [{"name": w.name, "description": w.description, "inputs": w.inputs,
             "steps": [{"id": s.id, "tool": s.tool} for s in w.steps]} for w in ag.WORKFLOWS.values()]


@app.post("/agent/run")
def agent_run(body: AgentIn, db: Db, who: Who, llm: Annotated[LLM, Depends(llm_dependency)]):
    if not body.goal.strip():
        raise HTTPException(422, "goal is required")
    r = ag.run_agent(ag.Ctx(db, who, llm), body.goal.strip(), body.max_steps)
    log_event(db, who.tenant, actor(who), "agent.run", {"run_id": r.id, "status": r.status})
    return ag.run_dict(r)


def optional_llm_dependency():
    try:
        return get_llm()
    except NoLLMConfigured:
        return None


@app.post("/agent/workflows/{name}/run")
def agent_workflow_run(name: str, body: WorkflowIn, db: Db, who: Who,
                       llm: Annotated[LLM | None, Depends(optional_llm_dependency)]):
    try:
        r = ag.run_workflow(ag.Ctx(db, who, llm, allow_writes=who.can_write), name, body.inputs)
    except ag.ToolError as e:
        raise HTTPException(422 if "unknown workflow" not in str(e) else 404, str(e)) from e
    log_event(db, who.tenant, actor(who), "agent.workflow", {"run_id": r.id, "name": name, "status": r.status})
    return ag.run_dict(r)


@app.get("/agent/runs")
def agent_runs(db: Db, who: Who, limit: int = 20):
    rows = (db.query(AgentRun).filter_by(tenant_id=who.tenant).order_by(AgentRun.id.desc())
            .limit(max(1, min(limit, 100))).all())
    return [ag.run_dict(r) for r in rows]



CONNECTOR_HTTP = default_http  # tests replace this with recorded responses


class SyncBody(BaseModel):
    token: str  # per-call OAuth access token; never stored
    deal: str | None = None
    limit: int = 50
    options: dict[str, str] = {}


@app.get("/connectors")
def list_connectors(who: Who, db: Db):
    connected = {r.connector for r in db.query(Connection).filter_by(tenant_id=who.tenant)}
    return status(connected)


@app.post("/connectors/{name}/sync")
def sync_connector(name: str, body: SyncBody, db: Db, who: Writer):
    cls = IMPLEMENTED.get(name)
    if cls is None:
        raise HTTPException(404, "connector not implemented")
    try:
        conn = cls(body.token, CONNECTOR_HTTP, **body.options)
        out = connector_sync(db, who, conn, (body.deal or "").strip() or None, max(1, min(body.limit, 500)))
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except (ConnectorError, ValueError, OSError) as e:
        raise HTTPException(502, f"connector failed: {e}") from e
    log_event(db, who.tenant, actor(who), "connector.sync",
              {"connector": name, "deal": body.deal, "ingested": len(out["ingested"])})
    return out


@app.get("/documents/{doc_id}/source")
def document_source(doc_id: str, db: Db, who: Who):
    """Link back to the original in the source system, for audit and citation."""
    _own_doc(db, who, doc_id)
    s = db.query(DocumentSource).filter_by(document_id=doc_id).order_by(DocumentSource.id.desc()).first()
    if s is None:
        raise HTTPException(404, "document was uploaded manually; no connector source")
    return {"connector": s.connector, "url": s.url, "version": s.version}


def _unrestricted(who: Principal) -> None:
    if who.restricted:
        raise HTTPException(403, "alerts cover the whole tenant; use an unrestricted key")


class AlertStatusIn(BaseModel):
    status: str


@app.post("/alerts/scan")
def alerts_scan(db: Db, who: Writer):
    _unrestricted(who)
    made = al.scan(db, who.tenant)
    log_event(db, who.tenant, actor(who), "alerts.scan", {"created": len(made)})
    return {"created": [al.alert_dict(a) for a in made]}


@app.get("/alerts/brief")
def alerts_brief(db: Db, who: Who, since: str):
    """Alerts raised since an ISO timestamp, counted by kind and severity, with the most urgent items first."""
    _unrestricted(who)
    return al.brief(db, who.tenant, since)


@app.get("/alerts")
def alerts_list(db: Db, who: Who, status: str | None = None):
    _unrestricted(who)
    q = db.query(Alert).filter_by(tenant_id=who.tenant)
    if status:
        q = q.filter_by(status=status)
    return [al.alert_dict(a) for a in q.order_by(Alert.id.desc()).limit(200)]


@app.post("/alerts/{alert_id}/status")
def alerts_status(alert_id: int, body: AlertStatusIn, db: Db, who: Writer):
    _unrestricted(who)
    try:
        a = al.set_status(db, who.tenant, alert_id, body.status)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if a is None:
        raise HTTPException(404, "not found")
    return al.alert_dict(a)


class DigestIn(BaseModel):
    to: list[str]


@app.post("/alerts/digest")
def alerts_digest(body: DigestIn, db: Db, who: Writer):
    """Email the alerts that have not been emailed yet to the given addresses."""
    _unrestricted(who)
    try:
        n = notify.send_digest(db, who.tenant, body.to)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except notify.MailNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except OSError as e:
        raise HTTPException(502, f"mail server error: {e}") from e
    log_event(db, who.tenant, actor(who), "alerts.digest", {"sent": n, "recipients": len(body.to)})
    return {"sent": n}


class ConnectionBody(BaseModel):
    connector: str
    token: str
    deal: str | None = None
    options: dict[str, str] = {}
    interval_minutes: int | None = None  # None = manual only


def _oauth_access_token(row: Connection) -> str:
    """Trade the stored refresh token for an access token. Providers may rotate the refresh token,
    so a new one is re-sealed onto the row (the caller commits)."""
    tok = oauth.refresh(oauth.config_for(row.connector), vault.unseal(row.token_sealed), CONNECTOR_HTTP)
    if tok.get("refresh_token"):
        row.token_sealed = vault.seal(tok["refresh_token"])
    return tok["access_token"]


def _run_connection(db: Session, who: Principal, row: Connection) -> dict:
    cls = IMPLEMENTED[row.connector]
    try:
        opts = json.loads(row.options)
        token = _oauth_access_token(row) if opts.pop("auth", None) == "oauth" else vault.unseal(row.token_sealed)
        conn = cls(token, CONNECTOR_HTTP, **opts)
        out = connector_sync(db, who, conn, row.deal)
        row.last_status = f"ok: {len(out['ingested'])} new, {out['unchanged']} unchanged"
    except (ConnectorError, vault.VaultError, ValueError, OSError, PermissionError) as e:
        out = {"error": str(e)}
        row.last_status = f"error: {e}"
    row.last_run = _now_iso()
    db.commit()
    return out


@app.post("/connections", status_code=201)
def create_connection(body: ConnectionBody, db: Db, who: Writer):
    if body.connector not in IMPLEMENTED:
        raise HTTPException(404, "connector not implemented")
    deal = (body.deal or "").strip() or None
    if who.restricted and deal not in who.deals:
        raise HTTPException(403, "deal is required and must be within this key's scope")
    if body.interval_minutes is not None and body.interval_minutes < 5:
        raise HTTPException(422, "interval_minutes must be at least 5")
    try:
        sealed = vault.seal(body.token)
    except vault.VaultError as e:
        raise HTTPException(503, str(e)) from e
    row = Connection(tenant_id=who.tenant, connector=body.connector, deal=deal, options=json.dumps(body.options),
                     token_sealed=sealed, interval_minutes=body.interval_minutes, created_by=actor(who))
    db.add(row)
    db.commit()
    log_event(db, who.tenant, actor(who), "connection.create", {"id": row.id, "connector": body.connector, "deal": deal})
    return {"id": row.id, "connector": row.connector, "deal": row.deal, "interval_minutes": row.interval_minutes}


def _visible_connections(db: Session, who: Principal):
    q = db.query(Connection).filter_by(tenant_id=who.tenant)
    rows = q.order_by(Connection.id).all()
    return [r for r in rows if not who.restricted or r.deal in who.deals]  # walled keys see only their deals


@app.get("/connections")
def list_connections(db: Db, who: Who):
    return [{"id": r.id, "connector": r.connector, "deal": r.deal, "interval_minutes": r.interval_minutes,
             "last_run": r.last_run, "last_status": r.last_status} for r in _visible_connections(db, who)]


@app.post("/connections/{cid}/sync")
def sync_saved_connection(cid: int, db: Db, who: Writer):
    row = next((r for r in _visible_connections(db, who) if r.id == cid), None)
    if row is None:
        raise HTTPException(404, "connection not found")
    out = _run_connection(db, who, row)
    if "error" in out:
        raise HTTPException(502, f"connector failed: {out['error']}")
    return out


@app.post("/connections/run-due")
def run_due_connections(db: Db, who: Writer):
    """Cron entry point: run every visible connection whose interval has elapsed. Call it every few minutes."""
    now = datetime.now(UTC)
    ran = []
    for r in _visible_connections(db, who):
        if r.interval_minutes is None:
            continue
        if r.last_run and now - datetime.fromisoformat(r.last_run) < timedelta(minutes=r.interval_minutes):
            continue
        _run_connection(db, who, r)
        ran.append({"id": r.id, "status": r.last_status})
    return {"ran": ran}


@app.post("/connectors/linkedin/import")
async def import_linkedin(file: Annotated[UploadFile, File()], db: Db, who: Writer,
                          deal: Annotated[str | None, Form()] = None):
    """Upload the zip from LinkedIn's data export. Same deal wall and source records as token syncs."""
    deal = (deal or "").strip() or None
    if who.restricted and deal not in who.deals:
        raise HTTPException(403, "deal is required and must be within this key's scope")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    try:
        out = connector_sync(db, who, LinkedInExport(data), deal)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "connector.sync",
              {"connector": "linkedin", "deal": deal, "ingested": len(out["ingested"])})
    return out


class OAuthStartBody(BaseModel):
    deal: str | None = None
    interval_minutes: int | None = None
    options: dict[str, str] = {}


class GSheetsPushBody(BaseModel):
    token: str  # per-call OAuth access token; never stored
    spreadsheet: str
    range: str = "Sheet1"
    entity: str | None = None


@app.post("/connectors/gsheets/push")
def gsheets_push(body: GSheetsPushBody, db: Db, who: Writer):
    """Write the facts this key can see into a sheet tab. Same visibility gate as /facts.xlsx."""
    conn = GoogleSheets(body.token, CONNECTOR_HTTP, spreadsheet=body.spreadsheet, range=body.range)
    try:
        n = conn.push(fact_rows(db, who.tenant, body.entity, visible_doc_ids(db, who)))
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    except OSError as e:
        raise HTTPException(502, f"connector failed: {e}") from e
    log_event(db, who.tenant, actor(who), "connector.push",
              {"connector": "gsheets", "entity": body.entity, "cells": n})
    return {"updated_cells": n}


@app.post("/oauth/{name}/start")
def oauth_start(name: str, body: OAuthStartBody, db: Db, who: Writer):
    """Returns the provider's consent URL. The signed state carries the tenant, key, deal wall and options,
    so the callback needs no bearer token."""
    if name not in IMPLEMENTED:
        raise HTTPException(404, "connector not implemented")
    deal = (body.deal or "").strip() or None
    if who.restricted and deal not in who.deals:
        raise HTTPException(403, "deal is required and must be within this key's scope")
    if body.interval_minutes is not None and body.interval_minutes < 5:
        raise HTTPException(422, "interval_minutes must be at least 5")
    try:
        state = oauth.sign_state({"tenant": who.tenant, "key": actor(who), "connector": name, "deal": deal,
                                  "interval": body.interval_minutes, "options": body.options})
        url = oauth.authorize_url(oauth.config_for(name), oauth.redirect_uri(name), state)
    except OAuthError as e:
        raise HTTPException(503, str(e)) from e
    return {"authorize_url": url}


@app.get("/oauth/{name}/callback", status_code=201)
def oauth_callback(name: str, code: str, state: str, db: Db):
    try:
        claims = oauth.verify_state(state)
        if claims.get("connector") != name:
            raise OAuthError("state was issued for another connector")
        tok = oauth.exchange_code(oauth.config_for(name), code, oauth.redirect_uri(name), CONNECTOR_HTTP)
    except OAuthError as e:
        raise HTTPException(400, str(e)) from e
    if not tok.get("refresh_token"):
        raise HTTPException(400, "provider returned no refresh token; consent must grant offline access")
    try:
        sealed = vault.seal(tok["refresh_token"])
    except vault.VaultError as e:
        raise HTTPException(503, str(e)) from e
    bind_tenant(db, claims["tenant"])  # no bearer token on this route: the signed state names the tenant
    row = Connection(tenant_id=claims["tenant"], connector=name, deal=claims.get("deal"),
                     options=json.dumps(dict(claims.get("options", {}), auth="oauth")), token_sealed=sealed,
                     interval_minutes=claims.get("interval"), created_by=claims["key"])
    db.add(row)
    db.commit()
    log_event(db, claims["tenant"], claims["key"], "connection.create",
              {"id": row.id, "connector": name, "deal": row.deal, "auth": "oauth"})
    return {"id": row.id, "connector": name, "deal": row.deal, "interval_minutes": row.interval_minutes}


class EdgarSearchIn(BaseModel):
    query: str
    forms: list[str] = ["10-K"]
    since: str
    until: str
    limit: int = 50


@app.post("/targets/search/edgar")
def targets_search_edgar(body: EdgarSearchIn, db: Db, who: Writer):
    """Candidates from EDGAR full-text search, cited to the filing. Not imported; see already_imported."""
    if not body.query.strip() or len(body.forms) > 5:
        raise HTTPException(422, "give a query and at most 5 forms")
    if not os.environ.get("SEC_USER_AGENT"):
        raise HTTPException(503, "set SEC_USER_AGENT (SEC rejects anonymous requests)")
    try:
        cands = ss_mod.search(body.query, body.forms, body.since, body.until)
    except Exception as e:  # network or SEC error: report, never guess
        raise HTTPException(502, f"EDGAR search failed: {e}") from e
    have = {r[0] for r in db.query(Target.source_ref).filter_by(tenant_id=who.tenant, source="sec").all()}
    items = [{"name": c.name, "cik": c.cik, "sic": c.sic, "form": c.form, "file_date": c.file_date,
              "source_url": c.filing_url, "company_url": c.company_url, "already_imported": c.cik in have}
             for c in cands[:min(max(body.limit, 1), 200)]]
    return {"total": len(cands), "items": items}


class CompaniesHouseSearchIn(BaseModel):
    query: str
    limit: int = 20


@app.post("/targets/search/companies-house")
def targets_search_companies_house(body: CompaniesHouseSearchIn, db: Db, who: Writer):
    """Live Companies House name search, cited to each company page. Not imported; see already_imported."""
    if not body.query.strip():
        raise HTTPException(422, "give a query")
    try:
        cands = chs_mod.search(body.query, body.limit)
    except Exception as e:  # network or site error: report, never guess
        raise HTTPException(502, f"Companies House search failed: {e}") from e
    have = {r[0] for r in db.query(Target.source_ref).filter_by(tenant_id=who.tenant,
                                                                 source="companies_house").all()}
    return {"items": [{"name": c.name, "number": c.number, "status": c.status, "address": c.address,
                       "source_url": c.company_url, "already_imported": c.number in have} for c in cands]}
