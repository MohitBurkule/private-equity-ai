import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import date as DateT
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import (
    add_on,
    answer_cache,
    audit_archive,
    chfeed,
    enrich,
    notify,
    opendata_tools,  # noqa: F401  (registers open-data agent tools)
    outbound,
)
from app import agent as ag
from app import alerts as al
from app import ch_search as chs_mod
from app import companies_house as ch_mod
from app import comps as comps_mod
from app import covenant_parse as covparse_mod
from app import ddq as ddq_mod
from app import ddq_llm as ddq_llm_mod
from app import debt_parse as debt_parse_mod
from app import derived as derived_mod
from app import firm_knowledge as fk
from app import flagship as flagship_mod
from app import fund_admin_facts as fund_admin_facts_mod
from app import html_doc as html_doc_mod
from app import jobs as jobs_mod
from app import lbo as lbo_mod
from app import legal as legal_mod
from app import lp_docs as lp_mod
from app import lp_tone as lp_tone_mod
from app import lp_waterfall as wf_lp_mod
from app import marketfeed_facts as marketfeed_facts_mod
from app import memo_diff as memo_diff_mod
from app import memo_templates as mt_mod
from app import notify as notify_mod
from app import otel as otel_mod
from app import outreach as outreach_mod
from app import peer_sets as peer_sets_mod
from app import peers as peers_mod
from app import people_enrich as pe_mod
from app import precedent_fetch as pfetch_mod
from app import precedents as prec_mod
from app import research as research_mod
from app import seen_before as seen_mod
from app import sourcing_search as ss_mod
from app import targets as tg_mod
from app import workflows as wf_mod
from app.acl import (
    Principal,
    acl_hidden_doc_ids,
    deal_hidden,
    deal_scope,
    doc_visible,
    fact_visible,
    format_groups,
    hidden_deal_names,
    mnpi_name_conflict,
    visible_doc_ids,
    visible_mnpi_deal_names,
)
from app.answer import answer_question
from app.audit import AuditEvent, log_event, verify_chain
from app.auth import (
    add_key,
    admin_token_ok,
    create_tenant,
    hash_key,
    key_id,
    list_keys,
    principal_for_identity,
    principal_for_key,
    revoke_key,
)
from app.calc import Calc, find_conflicts, ltm, net_debt, nwc
from app.calendar_events import retag_deals
from app.chat_alerts import chat_poster
from app.chat_inbound import (
    HELP,
    NOT_LINKED,
    chat_identity,
    format_answer,
    slack_question,
    slack_reply,
    teams_question,
    teams_reply,
    verify_slack,
    verify_teams,
)
from app.citations import quote_in_page
from app.comps import EV_METRIC
from app.connectors import oauth, vault
from app.connectors.base import ConnectorError, default_http
from app.connectors.docusign import DocuSign
from app.connectors.gsheets import GoogleSheets
from app.connectors.linkedin import LinkedInExport
from app.connectors.oauth import OAuthError
from app.connectors.registry import IMPLEMENTED, connection_health, status
from app.connectors.sync import sync as connector_sync
from app.crunchbase import read_funding_rounds_numbered
from app.db import make_engine, make_session_factory
from app.dd import STATUSES, TEMPLATE
from app.edgar import fetch_companyfacts
from app.email_links import EMAIL_CONNECTORS, links_for
from app.email_routing import unattached_emails
from app.envelope_stage import advance, deal_for_subject, parse_connect
from app.expert_calls import flags, parse
from app.extract.rows import _ROWS as ROW_SCHEMAS
from app.extract.rows import _blocks, extract_rows
from app.extract.run import extract_schema
from app.extract.schemas import SCHEMAS
from app.extract.tieout import tie_out
from app.facts import (
    CitationError,
    add_chart_fact,
    add_html_fact,
    add_verified_fact,
    review_fact,
)
from app.factsxlsx import build_facts_xlsx, fact_rows
from app.filing_view import filing_page_html
from app.funding_import import funding_for_target
from app.fundmetrics import fund_metrics
from app.holdings import parse_holdings
from app.hybrid import default_index
from app.ingest import finalize_upload, ingest_any
from app.ixbrl_full import read_filing
from app.kpi_workbook import ingest_kpi_pack as kpi_pack_ingest
from app.lbo_workbook import named_inputs, tie
from app.llm import LLM, LLMCapExceeded, NoLLMConfigured, get_llm, llm_id
from app.marketdata import NoData
from app.memo import build_memo, build_memo_docx, build_memo_pptx
from app.memo_templates import TEMPLATES, build_memo_sections
from app.migrate import migrate
from app.model_audit import audit
from app.models import (
    STAGES,
    AgentRun,
    Alert,
    ApiKey,
    CalendarEvent,
    Connection,
    DDQuestion,
    DDRequest,
    Deal,
    DealChecklistItem,
    DealDeletion,
    DealNote,
    DigestPref,
    Document,
    DocumentFile,
    DocumentSource,
    EvalRun,
    Fact,
    FactSource,
    Holding,
    HtmlUnit,
    ICDecision,
    IngestJob,
    LboRun,
    MemoComment,
    MemoTemplate,
    MemoVersion,
    OutreachItem,
    PageRow,
    PeerSet,
    Person,
    SavedScreen,
    SavedSearch,
    SyncRun,
    Target,
    TargetContact,
    TargetNote,
    ValuationRound,
    WorkflowSchedule,
)
from app.models import Tenant as TenantRow
from app.oidc import oidc_principal
from app.page_image import render_page
from app.parse import chart_vlm
from app.parse.sh01 import parse_capital_form
from app.portfolio import (
    MARK_METRIC,
    Covenant,
    KpiObservation,
    PortfolioCompany,
    add_covenant,
    budget_variance,
    compliance_summary,
    current_kpis,
    evaluate_covenant,
    qoq_change,
    record_observation,
    roll_forward,
)
from app.qoe import normalized_ebitda, nwc_peg, one_off_flags, revenue_trend
from app.ratelimit import make_limiter
from app.report import build_report, build_report_docx
from app.rls import apply_rls, bind_tenant, install_tenant_hook, verify_app_role
from app.shareledger import Event as LedgerEvent
from app.shareledger import reconcile as reconcile_shares
from app.stage_sync import stage_sync as run_stage_sync
from app.sumcheck import sum_check
from app.tracing import render_metrics, tracing_middleware
from app.valuation_rounds import parse_rounds
from app.versions import superseded
from app.waterfall import PrefClass, waterfall
from app.xbrl import candidates, crosscheck, load_companyfacts

engine = make_engine()
limiter = make_limiter(int(os.environ.get("RATE_LIMIT_PER_MIN", "600")), os.environ.get("REDIS_URL"), engine)
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
otel_mod.setup()


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
    identity: str | None = Field(default=None, max_length=256)  # the person's external id, e.g. their email
    groups: list[str] | None = None  # external group ids the person is in, e.g. Azure AD group object ids


class GroupSyncIn(BaseModel):
    token: str = Field(min_length=1, max_length=4096)  # a Graph token with directory read; used once, never stored


@app.post("/admin/tenants/{tenant_id}/keys/{kid}/groups/sync")
def admin_sync_key_groups(tenant_id: str, kid: str, body: GroupSyncIn, db: Db,
                          x_admin_token: Annotated[str | None, Header()] = None):
    """Set a key's groups from its person's directory memberships, so group grants apply without manual upkeep."""
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    row = next((k for k in db.query(ApiKey).filter_by(tenant_id=tenant_id) if key_id(k.key_hash) == kid), None)
    if row is None or row.revoked:
        raise HTTPException(404, "key not found")
    if not row.identity:
        raise HTTPException(422, "key has no identity to look up in the directory")
    from app.connectors.graph import DirectoryGroups
    try:
        groups = DirectoryGroups(body.token, CONNECTOR_HTTP).member_of(row.identity)
    except ConnectorError as e:
        raise HTTPException(502, str(e)) from e
    row.groups = format_groups(list(groups))
    db.commit()
    return {"key_id": kid, "groups": list(groups)}


@app.put("/admin/tenants/{tenant_id}/pii-redaction")
def admin_pii_redaction(tenant_id: str, body: dict, db: Db, x_admin_token: Annotated[str | None, Header()] = None):
    """Turn the tenant's PII flag on or off. Admin token only; the change is audited under the tenant."""
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    bind_tenant(db, tenant_id)  # no key here, so RLS would hide the tenant's rows unless bound to it
    t = db.get(TenantRow, tenant_id)
    if t is None:
        raise HTTPException(404, "tenant not found")
    if not isinstance(body.get("on"), bool):
        raise HTTPException(422, "body must be {\"on\": true or false}")
    t.pii_redaction = body["on"]
    db.commit()
    log_event(db, tenant_id, "admin", "tenant.pii_redaction", {"on": t.pii_redaction})
    return {"tenant_id": tenant_id, "pii_redaction": t.pii_redaction}


@app.post("/admin/tenants/{tenant_id}/keys", status_code=201)
def admin_add_key(tenant_id: str, db: Db, body: KeyIn | None = None, x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    if db.get(TenantRow, tenant_id) is None:
        raise HTTPException(404, "tenant not found")
    body = body or KeyIn()
    try:
        kid, key = add_key(db, tenant_id, body.role, body.deals, body.deal_roles, body.identity, body.groups)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"key_id": kid, "role": body.role, "deals": body.deals, "deal_roles": body.deal_roles, "api_key": key,
            "note": "store this key now; it is not shown again"}


@app.get("/admin/tenants/{tenant_id}/keys")
def admin_list_keys(tenant_id: str, db: Db, x_admin_token: Annotated[str | None, Header()] = None):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    if db.get(TenantRow, tenant_id) is None:
        raise HTTPException(404, "tenant not found")
    return {"keys": list_keys(db, tenant_id)}


@app.get("/admin/tenants/{tenant_id}/document-access")
def admin_document_access(tenant_id: str, db: Db, x_admin_token: Annotated[str | None, Header()] = None):
    """Synced documents whose source names who may read them, from the source's access list. Admin only: the
    list names people and groups, so it stays off the key-scoped screens. Documents without an access list are
    open to every key in the tenant and are not listed."""
    if not admin_token_ok(x_admin_token):
        raise HTTPException(403, "admin token required")
    if db.get(TenantRow, tenant_id) is None:
        raise HTTPException(404, "tenant not found")
    bind_tenant(db, tenant_id)  # no key here, so RLS would hide the tenant's rows unless bound to it
    rows = (db.query(DocumentSource, Document)
            .join(Document, Document.id == DocumentSource.document_id)
            .filter(DocumentSource.tenant_id == tenant_id, DocumentSource.acl.isnot(None))
            .order_by(Document.filename).all())
    docs = [{"document_id": d.id, "filename": d.filename, "deal": d.deal, "connector": src.connector,
             "grants": json.loads(src.acl)} for src, d in rows]
    return {"documents": docs, "restricted": len(docs)}


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
            "progress": {"files_done": j.files_done, "files_total": j.files_total, "current_file": j.current_file},
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
    if not doc_visible(doc, who, hidden_deal_names(db, who)) or doc_id in acl_hidden_doc_ids(db, who):
        # same 404 for "missing", "other tenant", "behind a wall", "not on the source's access list"
        raise HTTPException(404, "document not found")
    if doc.deal and doc.deal in visible_mnpi_deal_names(db, who):
        log_event(db, who.tenant, actor(who), "document.mnpi_access", {"doc_id": doc.id, "deal": doc.deal})
    # Every route that opens a document goes through here, so every read leaves a line in the trail.
    # With AUDIT_READ_DEDUPE on, a repeat read by the same person in the same hour adds no line.
    if not audit_archive.read_dedupe_on() or not audit_archive.read_logged_this_hour(
            db, who.tenant, actor(who), doc.id):
        log_event(db, who.tenant, actor(who), "document.read", {"doc_id": doc.id, "deal": doc.deal})
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


class BulkDealIn(BaseModel):
    doc_ids: list[str]
    deal: str | None = None  # None takes the documents off their deal


@app.post("/documents/bulk-deal")
def documents_bulk_deal(body: BulkDealIn, db: Db, who: Writer):
    """Move many documents to one deal (or off it). Each document is checked on its own: it must be visible to the
    caller, and the caller must hold write on the deal it leaves and on the deal it joins. A refused document is
    reported with its reason and the rest still move. Every move is written to the audit trail."""
    if len(body.doc_ids) > 200:
        raise HTTPException(422, "too many documents")
    if body.deal:
        _visible_deal_or_404(db, who, body.deal)
    hidden = hidden_deal_names(db, who)
    acl_hidden = acl_hidden_doc_ids(db, who)
    moved, refused = [], []
    for doc_id in body.doc_ids:
        doc = db.get(Document, doc_id)
        if not doc_visible(doc, who, hidden) or doc_id in acl_hidden:
            refused.append({"doc_id": doc_id, "reason": "document not found"})
            continue
        if not (who.can("write", doc.deal) and (body.deal is None or who.can("write", body.deal))):
            refused.append({"doc_id": doc_id, "reason": "needs write on the source and target deal"})
            continue
        before = doc.deal
        doc.deal = body.deal
        log_event(db, who.tenant, actor(who), "document.bulk_deal",
                  {"doc_id": doc.id, "from": before, "to": body.deal,
                   "deals": [d for d in (before, body.deal) if d]})  # the deal report matches on these
        moved.append(doc_id)
    db.commit()
    return {"moved": moved, "refused": refused}


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


@app.post("/documents/{doc_id}/chart-facts", status_code=201)
def chart_facts(doc_id: str, entity: str, period: str, db: Db, who: Writer,
                metric: str = "chart value", unit: str = "as printed"):
    """Values the chart model reads off the document's charts. Stored as ocr_unverified only, each citing its
    page and label bbox. A value matched on the page text alone has no bbox on the chart, so it is skipped."""
    doc = _own_doc(db, who, doc_id)
    original = db.get(DocumentFile, doc.id)
    if original is None:
        raise HTTPException(409, "original file not stored")
    created, skipped = [], []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.pdf"
        path.write_bytes(original.data)
        for page in range(1, doc.n_pages + 1):
            for v in chart_vlm.extract_vlm_values(path, page):
                if not v.verified:
                    skipped.append({"page": page, "label": v.text, "reason": "not matched on the chart or page text"})
                    continue
                if v.bbox is None:
                    skipped.append({"page": page, "label": v.text, "reason": "matched page text only, no bbox to cite"})
                    continue
                try:
                    fact = add_chart_fact(db, tenant_id=who.tenant, entity=entity, metric=metric, period=period,
                                          value=Decimal(str(v.value)), unit=unit, document_id=doc.id, page=page,
                                          label=v.text, bbox=v.bbox)
                except CitationError as e:
                    skipped.append({"page": page, "label": v.text, "reason": str(e)})
                    continue
                created.append(fact.id)
    log_event(db, who.tenant, actor(who), "chart_facts", {"document_id": doc.id, "created": created})
    return {"created": created, "skipped": skipped}


@app.post("/documents/{doc_id}/fund-admin/facts", status_code=201)
def fund_admin_facts(doc_id: str, entity: str, db: Db, who: Writer):
    """Capital calls and NAV read from a fund-admin workbook or a capital-call notice (templates in app/fundadmin.py)
    as facts. Each one is
    cited to its cell through the same citation gate as /facts. Rows that do not match the template are skipped."""
    doc = _own_doc(db, who, doc_id)
    created, skipped = fund_admin_facts_mod.extract_facts(db, who.tenant, doc, entity)
    log_event(db, who.tenant, actor(who), "fund_admin.facts", {"document_id": doc.id, "created": created})
    return {"created": created, "skipped": skipped}


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
    acl_hidden = acl_hidden_doc_ids(db, who)  # the same test _own_doc applies, so a listed name always opens
    return [{"id": d.id, "filename": d.filename, "n_pages": d.n_pages, "deal": d.deal}
            for d in db.query(Document).filter_by(tenant_id=who.tenant).all()
            if doc_visible(d, who, hidden) and d.id not in acl_hidden]


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
            "sources": [{"document_id": s.document_id, "page": s.page, "locator": s.locator,
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
                        "sources": [{"document_id": s.document_id, "page": s.page, "locator": s.locator,
                                     "quote": s.quote} for s in i.fact.sources]}
                       for i in c.inputs]}


@app.get("/facts/derived")
def fact_derived(db: Db, who: Who, formula: str, entity: str, period: str):
    """A derived value with every component's citation. Recomputed on each call; never stored."""
    try:
        d = derived_mod.derive(db, who.tenant, visible_doc_ids(db, who), formula, entity, period)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"formula": d.formula, "entity": d.entity, "period": d.period, "unit": d.unit, "value": str(d.value),
            "components": [{"fact_id": c.fact_id, "metric": c.metric, "value": str(c.value), "sources": c.sources}
                           for c in d.components]}


@app.get("/facts/conflicts")
def fact_conflicts(db: Db, who: Who, entity: str | None = None, cross_document_only: bool = False):
    """Same entity, metric, period and basis with different values across facts. Reports only."""
    out = []
    for c in find_conflicts(db, who.tenant, visible_doc_ids(db, who), entity):
        if not (c.cross_document or not cross_document_only):
            continue
        # A newer version of the same model is a restatement candidate, not an error: report which document
        # supersedes which so the reviewer does not chase a v3-vs-v5 difference as a conflict.
        names = {d["document_id"]: d["filename"] for s in c.sources for d in s["documents"]}
        newer = superseded({k: v for k, v in names.items() if v})
        out.append({"entity": c.entity, "metric": c.metric, "period": c.period, "basis": c.basis,
                    "spread_pct": str(c.spread_pct.quantize(Decimal("0.01"))), "likely_rounding": c.likely_rounding,
                    "severity": c.severity, "cross_document": c.cross_document, "sources": c.sources,
                    "values": [{"value": str(v), "fact_id": fid} for v, fid in c.values],
                    "superseded_by": {str(k): str(v) for k, v in newer.items()}})
    return out


def get_market_fetch():
    from app.marketfeeds import default_fetch
    return default_fetch


class TevSyncIn(BaseModel):
    entity: str
    period: str
    source: str
    url: str
    token: str


@app.post("/market/tev-sync")
def market_tev_sync(body: TevSyncIn, db: Db, who: Writer, fetch: Annotated[Callable, Depends(get_market_fetch)]):
    """Enterprise value from a market-data feed, saved as a cited fact that trading comps read."""
    try:
        f = marketfeed_facts_mod.sync_tev(db, who.tenant, entity=body.entity, period=body.period, source=body.source,
                                          url=body.url, token=body.token, fetch=fetch)
    except (NoData, CitationError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return {"fact_id": f.id, "metric": f.metric, "value": str(f.value), "unit": f.unit,
            "quote": f.sources[0].quote, "document_id": f.sources[0].document_id}


class TevRefreshIn(BaseModel):
    items: list[TevSyncIn]


@app.post("/market/tev-refresh")
def market_tev_refresh(body: TevRefreshIn, db: Db, who: Writer, fetch: Annotated[Callable, Depends(get_market_fetch)]):
    """Re-pull enterprise value for many entities in one call. Each item stands alone: a failed feed is reported
    on its own line and never stops the others or leaves a half-written fact."""
    if len(body.items) > 50:
        raise HTTPException(422, "too many items")
    out = []
    for it in body.items:
        try:
            f = marketfeed_facts_mod.sync_tev(db, who.tenant, entity=it.entity, period=it.period, source=it.source,
                                              url=it.url, token=it.token, fetch=fetch)
            db.commit()
            out.append({"entity": it.entity, "ok": True, "fact_id": f.id, "value": str(f.value), "unit": f.unit,
                        "as_of": f.as_of})
        except (NoData, CitationError, ValueError) as e:
            db.rollback()
            out.append({"entity": it.entity, "ok": False, "error": str(e)})
    return {"results": out}


@app.post("/lbo/returns")
def lbo_returns(body: dict, db: Db, who: Who, fetch: Annotated[Callable, Depends(get_market_fetch)],
                xlsx: bool = False):
    """Sponsor returns from cited inputs. Each input is {"value", "source": {document_id, page, quote}}
    or {"fact_id"}; an uncited input is refused. {"rate_series": {"series", "margin_pct"}} takes the newest
    published value of a macro series (e.g. SOFR) plus a margin, cited to the series and its date."""
    raw = body.get("inputs") or {}
    scope = visible_doc_ids(db, who)
    cited: dict[str, lbo_mod.Cited] = {}
    for name, spec in raw.items():
        if "rate_series" in spec:
            from app.macrodata import FredProvider, rate_with_margin
            from app.marketdata import NoData
            rs = spec["rate_series"] or {}
            try:
                value, src = rate_with_margin(FredProvider(fetch=fetch), rs.get("series", ""), rs.get("margin_pct", "0"))
            except NoData as e:
                raise HTTPException(422, f"{name}: {e}") from e
            except OSError as e:
                raise HTTPException(502, f"{name}: rate source unreachable: {e}") from e
            cited[name] = lbo_mod.Cited(value, src)
        elif "fact_id" in spec:
            f = db.query(Fact).filter(Fact.id == spec["fact_id"], Fact.tenant_id == who.tenant).first()
            if f is None or not fact_visible(f, scope) or not f.sources or f.status != "verified":
                raise HTTPException(422, f"{name}: fact not found, not verified, or has no source")
            names = {d.id: d.filename for d in db.query(Document).filter(
                Document.id.in_({s.document_id for s in f.sources}))}
            src = {"document_id": f.sources[0].document_id, "filename": names.get(f.sources[0].document_id),
                   "page": f.sources[0].page, "quote": f.sources[0].quote}
            cited[name] = lbo_mod.Cited(f.value, src)
        elif "derived" in spec:
            # A derived input is computed from its components, each of which carries its own citation.
            d = spec["derived"] or {}
            try:
                dv = derived_mod.derive(db, who.tenant, scope, d.get("formula", ""), d.get("entity", ""), d.get("period", ""))
            except ValueError as e:
                raise HTTPException(422, f"{name}: {e}") from e
            first = dv.components[0].sources[0]
            src = {"derived": True, "formula": dv.formula, "document_id": first["document_id"], "page": first["page"],
                   "quote": first["quote"], "components": [c.fact_id for c in dv.components]}
            cited[name] = lbo_mod.Cited(dv.value, src)
        elif "assumption" in spec:
            # An assumption is a judgement, not a fact: it names who set it, when and why, and never passes the
            # citation gate. Outputs list every assumption so it cannot pass as sourced.
            a = spec["assumption"] or {}
            if not a.get("set_by") or not a.get("set_on") or not a.get("reason"):
                raise HTTPException(422, f"{name}: assumption needs set_by, set_on and reason")
            src = {"assumption": True, "set_by": a["set_by"], "set_on": a["set_on"], "reason": a["reason"]}
            cited[name] = lbo_mod.Cited(Decimal(str(spec["value"])), src)
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
        data = lbo_mod.build_xlsx(cited, res, grid)
        if outbound.pii_on(db, who.tenant):
            data = outbound.xlsx(data)
        return Response(data, headers={
            "Content-Disposition": 'attachment; filename="lbo_returns.xlsx"'},
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return {"entry_ev": str(res.entry_ev), "debt": str(res.debt), "fees": str(res.fees),
            "equity": str(res.equity), "exit_ev": str(res.exit_ev), "exit_net_debt": str(res.exit_net_debt),
            "exit_equity": str(res.exit_equity), "moic": str(res.moic.quantize(Decimal("0.01"))),
            "irr": None if res.irr is None else str(res.irr.quantize(Decimal("0.0001"))),
            "dividends": str(res.dividends), "schedule": res.schedule, "sensitivity": grid,
            "derived": [{"input": k, "formula": c.source["formula"], "components": c.source["components"]}
                        for k, c in cited.items() if c.source.get("derived")],
            "assumptions": [{"input": k, "value": str(c.value), "set_by": c.source["set_by"],
                             "set_on": c.source["set_on"], "reason": c.source["reason"]}
                            for k, c in cited.items() if c.source.get("assumption")],
            "base_rates": [{"input": k, "value": str(c.value), **{f: c.source[f] for f in ("series", "as_of", "base_value", "source", "quote")}}
                           for k, c in cited.items() if c.source.get("macro")]}


def _lbo_run_row(r: LboRun) -> dict:
    res = json.loads(r.result)
    return {"id": r.id, "name": r.name, "created_at": r.created_at, "created_by": r.created_by,
            "moic": res["moic"], "irr": res["irr"], "entry_ev": res["entry_ev"], "exit_equity": res["exit_equity"]}


@app.post("/lbo/runs")
def lbo_save(body: dict, db: Db, who: Who, fetch: Annotated[Callable, Depends(get_market_fetch)]):
    """Save an LBO run. The request is re-run through /lbo/returns first, so a saved run passed the same
    citation gate and its stored result is the one it produced now."""
    name = str(body.get("name") or "").strip()[:128]
    if not name:
        raise HTTPException(422, "name is required")
    request = body.get("request") or {}
    result = lbo_returns(request, db, who, fetch)
    row = LboRun(tenant_id=who.tenant, name=name, created_by=who.key_id, created_at=_now_iso(),
                 request=json.dumps(request), result=json.dumps(result, default=str))
    db.add(row)
    db.commit()
    return _lbo_run_row(row)


@app.get("/lbo/runs")
def lbo_list(db: Db, who: Who):
    rows = db.query(LboRun).filter(LboRun.tenant_id == who.tenant).order_by(LboRun.id.desc()).all()
    return [_lbo_run_row(r) for r in rows]


@app.get("/lbo/runs/{run_id}")
def lbo_get(run_id: int, db: Db, who: Who):
    r = db.query(LboRun).filter(LboRun.id == run_id, LboRun.tenant_id == who.tenant).first()
    if r is None:
        raise HTTPException(404, "run not found")
    return {**_lbo_run_row(r), "request": json.loads(r.request), "result": json.loads(r.result)}


@app.get("/calc/normalized-ebitda")
def calc_normalized_ebitda(entity: str, period: str, db: Db, who: Who):
    """Reported EBITDA plus reviewed add-backs, less deductions. Withheld while any bridge line is unreviewed;
    add-backs above 10% of reported EBITDA come back as one-off flags for a person to check."""
    c = normalized_ebitda(db, who.tenant, entity, period, visible_doc_ids(db, who))
    return {**_calc_out(c), "one_off_flags": one_off_flags(c)}


@app.get("/calc/ltm")
def calc_ltm(entity: str, metric: str, fy: str, ytd: str, ytd_prior: str, db: Db, who: Who):
    return _calc_out(ltm(db, who.tenant, entity, metric, fy, ytd, ytd_prior, visible_doc_ids(db, who)))


@app.get("/calc/net-debt")
def calc_net_debt(entity: str, period: str, db: Db, who: Who, include_leases: bool = True):
    return _calc_out(net_debt(db, who.tenant, entity, period, visible_doc_ids(db, who), include_leases))


@app.get("/calc/periods")
def calc_periods(entity: str, db: Db, who: Who):
    """Periods that have verified facts for the entity, oldest first, so a screen can default to ones that exist."""
    visible = visible_doc_ids(db, who)
    rows = db.query(Fact).filter_by(tenant_id=who.tenant, entity=entity, status="verified").all()
    periods = {f.period for f in rows if fact_visible(f, visible)}
    return {"entity": entity, "periods": sorted(periods)}


@app.get("/calc/revenue-trend")
def calc_revenue_trend(entity: str, periods: str, db: Db, who: Who):
    """Revenue growth and normalized EBITDA margin across comma-separated periods, oldest first."""
    wanted = [p.strip() for p in periods.split(",") if p.strip()]
    return {"entity": entity, "rows": revenue_trend(db, who.tenant, entity, wanted, visible_doc_ids(db, who))}


@app.get("/calc/nwc-peg")
def calc_nwc_peg(entity: str, periods: str, db: Db, who: Who):
    """Trailing-average NWC peg. `periods` is comma-separated, e.g. FY22,FY23,FY24."""
    wanted = [p.strip() for p in periods.split(",") if p.strip()]
    scope = visible_doc_ids(db, who)
    out = _calc_out(nwc_peg(db, who.tenant, entity, wanted, scope))
    out["per_period"] = {p: _calc_out(nwc(db, who.tenant, entity, p, scope)) for p in wanted}
    return out


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


class DDQuestionIn(BaseModel):
    deal: str
    question: str
    request_id: int | None = None


class DDQuestionUpdate(BaseModel):
    answer: str | None = None
    document_id: str | None = None
    page: int | None = None
    quote: str | None = None


def _dd_question_out(q: DDQuestion) -> dict:
    return {"id": q.id, "deal": q.deal, "request_id": q.request_id, "question": q.question, "status": q.status,
            "answer": q.answer, "document_id": q.document_id, "page": q.page, "quote": q.quote,
            "asked_at": q.asked_at, "answered_at": q.answered_at}


@app.post("/dd/questions", status_code=201)
def dd_question_add(body: DDQuestionIn, db: Db, who: Writer):
    if not _dd_scope_ok(who, body.deal):
        raise HTTPException(403, "deal is outside this key's scope")
    if body.request_id is not None and db.query(DDRequest).filter_by(
            tenant_id=who.tenant, id=body.request_id, deal=body.deal).first() is None:
        raise HTTPException(422, "request_id is not on this deal's request list")
    q = DDQuestion(tenant_id=who.tenant, deal=body.deal, request_id=body.request_id, question=body.question,
                   asked_at=_now_iso())
    db.add(q)
    db.commit()
    return _dd_question_out(q)


@app.get("/dd/questions")
def dd_question_list(db: Db, who: Who, deal: str | None = None, status: str | None = None):
    q = db.query(DDQuestion).filter_by(tenant_id=who.tenant)
    if deal:
        q = q.filter_by(deal=deal)
    if status:
        q = q.filter_by(status=status)
    return [_dd_question_out(r) for r in q.order_by(DDQuestion.id).all() if _dd_scope_ok(who, r.deal)]


@app.patch("/dd/questions/{qid}")
def dd_question_update(qid: int, body: DDQuestionUpdate, db: Db, who: Writer):
    """Records an answer. An answer must cite a document the key can see, a page or block in it, and a quote that is
    printed there: the same gate a fact passes. A cited quote that is not on the page is refused, so an answer
    cannot point at a source that does not say it."""
    q = db.query(DDQuestion).filter_by(tenant_id=who.tenant, id=qid).first()
    if q is None or not _dd_scope_ok(who, q.deal):
        raise HTTPException(404, "question not found")
    if body.answer is not None:
        if not body.answer.strip():
            raise HTTPException(422, "answer is empty")
        if body.document_id is None or body.page is None or not body.quote:
            raise HTTPException(422, "an answer needs a document, a page and the quote it came from")
        scope = visible_doc_ids(db, who)  # None = unrestricted key
        doc = db.query(Document).filter_by(tenant_id=who.tenant, id=body.document_id).first()
        if doc is None or (scope is not None and doc.id not in scope):
            raise HTTPException(422, "document is not visible to this key")
        blocks = _blocks(db, doc)
        if body.page not in blocks:
            raise HTTPException(422, "page not found in the document")
        if not quote_in_page(body.quote, blocks[body.page]):
            raise HTTPException(422, "quote not found on the cited page")
        q.answer = body.answer
        q.status = "answered"
        q.answered_at = _now_iso()
        q.document_id = doc.id
        q.page = body.page
        q.quote = body.quote
    elif body.document_id is not None:
        raise HTTPException(422, "a document can only be set together with an answer")
    db.commit()
    return _dd_question_out(q)
class ExpertCallIn(BaseModel):
    transcript: str


@app.post("/dd/expert-calls/review")
def expert_call_review(body: ExpertCallIn, who: Who):
    """Turns of an expert-call transcript and the lines a compliance reviewer should read first. Stores nothing:
    the transcript is the caller's, and the flags are a prompt for review, not a finding."""
    turns = parse(body.transcript)
    return {"turns": len(turns), "speakers": sorted({t.speaker for t in turns}),
            "flags": [{"line": f.line, "speaker": f.speaker, "phrase": f.phrase, "quote": f.quote}
                      for f in flags(turns)]}


@app.post("/lbo/workbook/ties")
async def lbo_workbook_ties(file: Annotated[UploadFile, File()], db: Db, who: Who):
    """Named inputs of an LBO workbook, each tied to verified facts with the same value. Untied inputs are
    flagged for a person; the workbook's value is never changed. Also lists required LBO inputs it lacks."""
    inputs = named_inputs(await file.read())
    ties = tie(db, who.tenant, visible_doc_ids(db, who), inputs)
    lbo_missing = sorted(k for k in lbo_mod.REQUIRED if k not in inputs)
    return {"inputs": ties, "untied": sorted(k for k, v in ties.items() if v["tie"] == "untied"),
            "lbo_missing": lbo_missing}


@app.post("/models/audit")
async def model_audit(file: Annotated[UploadFile, File()], who: Who):
    """Hardcodes in formula rows, #REF! references and external links in an Excel model. Stores nothing."""
    return {"findings": audit(await file.read())}


OUTCOMES = {"proceed", "pass", "hold", "more_diligence"}


class ICDecisionIn(BaseModel):
    deal: str
    outcome: str
    rationale: str = Field(min_length=1)
    dissent: str | None = None
    dissenter: str | None = None


def _decision_out(d: ICDecision) -> dict:
    return {"id": d.id, "deal": d.deal, "outcome": d.outcome, "rationale": d.rationale, "dissent": d.dissent,
            "dissenter": d.dissenter, "recorded_at": d.recorded_at}


@app.post("/ic/decisions", status_code=201)
def ic_decision_add(body: ICDecisionIn, db: Db, who: Writer):
    """Appends a decision. There is no edit or delete: a changed view is a new entry."""
    if not _dd_scope_ok(who, body.deal):
        raise HTTPException(403, "deal is outside this key's scope")
    if body.outcome not in OUTCOMES:
        raise HTTPException(422, f"outcome must be one of {sorted(OUTCOMES)}")
    d = ICDecision(tenant_id=who.tenant, deal=body.deal, outcome=body.outcome, rationale=body.rationale,
                   dissent=body.dissent, dissenter=body.dissenter, recorded_at=_now_iso())
    db.add(d)
    db.commit()
    return _decision_out(d)


@app.get("/ic/decisions")
def ic_decision_list(deal: str, db: Db, who: Who):
    if not _dd_scope_ok(who, deal):
        raise HTTPException(403, "deal is outside this key's scope")
    rows = db.query(ICDecision).filter_by(tenant_id=who.tenant, deal=deal).order_by(ICDecision.id).all()
    return [_decision_out(d) for d in rows]


@app.get("/ic/review")
def ic_review(deal: str, db: Db, who: Who):
    """The IC pack's record view: the latest decision, the dissents on file, and the documents filed since that
    decision. Documents are filtered as the document list is, so a walled file never shows up as a change."""
    if not _dd_scope_ok(who, deal):
        raise HTTPException(403, "deal is outside this key's scope")
    rows = db.query(ICDecision).filter_by(tenant_id=who.tenant, deal=deal).order_by(ICDecision.id).all()
    latest = rows[-1] if rows else None
    hidden = hidden_deal_names(db, who)
    docs = [d for d in db.query(Document).filter_by(tenant_id=who.tenant, deal=deal).all()
            if doc_visible(d, who, hidden)]
    since = []
    if latest is not None:
        # Compare instants, not strings: the two timestamps are written by different code paths.
        cut = datetime.fromisoformat(latest.recorded_at)
        since = [{"document_id": d.id, "filename": d.filename, "created_at": d.created_at}
                 for d in sorted(docs, key=lambda d: d.created_at or "")
                 if d.created_at and datetime.fromisoformat(d.created_at) > cut]
    return {"deal": deal, "latest": _decision_out(latest) if latest else None,
            "dissents": [_decision_out(d) for d in rows if d.dissent],
            "changed_since_ic": since, "ic_recorded": latest is not None}


@app.get("/deals/{name}/snapshot")
def deal_snapshot(name: str, db: Db, who: Who):
    """One-page partner view of a deal: stage, the latest IC outcome and dissent count, what was filed since that
    decision, documents, DD progress, open alerts and notes. Built from the same routes the workspace uses, so the
    numbers agree with the screens; nothing here is estimated."""
    d = _visible_deal_or_404(db, who, name)
    review = ic_review(name, db, who)
    latest = review["latest"]
    hidden = hidden_deal_names(db, who)
    docs = [x for x in db.query(Document).filter_by(tenant_id=who.tenant, deal=name).all()
            if doc_visible(x, who, hidden)]
    docs.sort(key=lambda x: x.created_at or "", reverse=True)
    dd = dd_summary(name, db, who)
    dd = {k: dd[k] for k in ("total", "closed", "pct_complete")}
    open_alerts = db.query(Alert).filter_by(tenant_id=who.tenant, deal=name, status="new").count()
    notes = db.query(DealNote).filter_by(tenant_id=who.tenant, deal=name).count()
    return {
        "deal": d.name, "stage": d.stage, "sic": d.sic, "sponsor": d.sponsor, "legal_hold": bool(d.legal_hold),
        "ic": {"recorded": review["ic_recorded"], "latest": latest,
               "dissents": len(review["dissents"]), "changed_since_ic": len(review["changed_since_ic"]),
               "changed_documents": review["changed_since_ic"][:5]},
        "documents": {"count": len(docs), "latest": [{"id": x.id, "filename": x.filename} for x in docs[:5]]},
        "dd": dd,
        "open_alerts": open_alerts,
        "notes": notes,
    }


@app.get("/ic/precedents")
def ic_precedents(deal: str, db: Db, who: Who):
    """Past IC outcomes for deals at the same stage in this tenant, and the same SIC code when the target has one.
    Only deals this key may see are compared: walled MNPI deals and other scopes are left out, and no other tenant
    is ever read."""
    if not _dd_scope_ok(who, deal):
        raise HTTPException(403, "deal is outside this key's scope")
    target = db.query(Deal).filter_by(tenant_id=who.tenant, name=deal).one_or_none()
    stage = target.stage if target else None
    visible = deal_scope(db, who)
    if target is None or (visible is not None and deal not in visible):
        raise HTTPException(404, "deal not found")
    # A SIC match is the stronger comparison, so it is required when the target has one. Without one, stage alone.
    match = "sic+stage" if target.sic else "stage"
    peers = [d.name for d in db.query(Deal).filter_by(tenant_id=who.tenant, stage=stage).all()
             if d.name != deal and (visible is None or d.name in visible)
             and (not target.sic or d.sic == target.sic)]
    rows = db.query(ICDecision).filter(ICDecision.tenant_id == who.tenant,
                                       ICDecision.deal.in_(peers)).order_by(ICDecision.id).all() if peers else []
    latest: dict[str, ICDecision] = {}
    for r in rows:
        latest[r.deal] = r  # rows are in id order, so the last one per deal is its current view
    counts: dict[str, int] = {}
    for r in latest.values():
        counts[r.outcome] = counts.get(r.outcome, 0) + 1
    return {"deal": deal, "stage": stage, "sic": target.sic, "match": match,
            "precedents": [_decision_out(latest[n]) for n in sorted(latest)],
            "outcome_counts": counts, "compared_deals": len(peers)}


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    organisation: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    expertise: list[str] | None = None
    deal: str | None = None  # sourced for this deal: visible only to keys that can see the deal


def _person_out(p: Person) -> dict:
    return {"id": p.id, "name": p.name, "organisation": p.organisation, "title": p.title,
            "expertise": [t.strip() for t in (p.expertise or "").split(",") if t.strip()], "deal": p.deal,
            "recorded_at": p.recorded_at}


@app.post("/people", status_code=201)
def person_add(body: PersonIn, db: Db, who: Writer):
    if body.deal:
        _visible_deal_or_404(db, who, body.deal)
        _require(who, "write", "record an expert for this deal", deal=body.deal)
    p = Person(tenant_id=who.tenant, name=body.name.strip(), organisation=body.organisation, title=body.title,
               expertise=", ".join(dict.fromkeys(t.strip() for t in body.expertise or [] if t.strip())) or None,
               deal=body.deal, recorded_at=_now_iso())
    db.add(p)
    db.commit()
    log_event(db, who.tenant, actor(who), "person.add", {"id": p.id, "deal": body.deal})
    return _person_out(p)


@app.get("/people")
def person_search(db: Db, who: Who, q: str = Query("", max_length=200), deal: str | None = None):
    """Experts and contacts matching q in name, organisation, title or expertise. Experts sourced for a deal the
    caller cannot see are left out, and so is a deal filter the caller has no right to."""
    needle = q.strip().lower()
    visible = deal_scope(db, who)
    if deal and visible is not None and deal not in visible:
        raise HTTPException(404, "deal not found")
    rows = db.query(Person).filter_by(tenant_id=who.tenant)
    if deal:
        rows = rows.filter(Person.deal == deal)
    out = []
    for p in rows.order_by(Person.id).all():
        if p.deal and (visible is not None and p.deal not in visible):
            continue
        hay = " ".join(x or "" for x in (p.name, p.organisation, p.title, p.expertise)).lower()
        if needle and needle not in hay:
            continue
        out.append(_person_out(p))
        if len(out) == 100:
            break
    return {"query": q, "people": out}


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
    sic: str | None = None
    sponsor: str | None = None
    aliases: list[str] | None = None
    cik: str | None = None
    lei: str | None = None


def _aliases_text(names: list[str] | None) -> str | None:
    clean = [n.strip() for n in (names or []) if n and n.strip()]
    return ", ".join(dict.fromkeys(clean)) or None  # dedupe, keep the order given


def _aliases_list(raw: str | None) -> list[str]:
    return [n.strip() for n in raw.split(",") if n.strip()] if raw else []


def _cik(raw: str | None) -> str | None:
    """SEC CIKs are numeric; stored without leading zeros so 0001234 and 1234 are the same registrant."""
    v = (raw or "").strip()
    if not v:
        return None
    if not v.isdigit() or len(v) > 10:
        raise HTTPException(422, "cik must be up to 10 digits")
    return v.lstrip("0") or "0"


def _lei(raw: str | None) -> str | None:
    v = (raw or "").strip().upper()
    if not v:
        return None
    if len(v) != 20 or not v.isalnum():
        raise HTTPException(422, "lei must be 20 letters or digits")
    return v


class DealUpdate(BaseModel):
    stage: str | None = None
    note: str | None = None
    legal_hold: bool | None = None
    mnpi: bool | None = None
    sic: str | None = None
    sponsor: str | None = None
    aliases: list[str] | None = None
    cik: str | None = None
    lei: str | None = None


def _deal_out(db: Session, who: Principal, d: Deal) -> dict:
    dd = db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=d.name).all()
    docs = db.query(Document).filter_by(tenant_id=who.tenant, deal=d.name).count()
    closed = sum(r.status != "open" for r in dd)
    return {"name": d.name, "stage": d.stage, "sic": d.sic, "sponsor": d.sponsor,
            "aliases": _aliases_list(d.aliases), "cik": d.cik,
            "lei": d.lei, "note": d.note, "legal_hold": d.legal_hold, "mnpi": d.mnpi, "updated_at": d.updated_at,
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
             sic=(body.sic or "").strip() or None, sponsor=(body.sponsor or "").strip() or None,
             aliases=_aliases_text(body.aliases), cik=_cik(body.cik),
             lei=_lei(body.lei),
             created_by=who.key_id if body.mnpi else None, updated_at=_now_iso())
    db.add(d)
    db.commit()
    retag_deals(db, who.tenant)  # meetings already stored may name the new deal
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


class DealNoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


def _note_out(n: DealNote) -> dict:
    return {"id": n.id, "deal": n.deal, "author": n.author, "body": n.body, "created_at": n.created_at,
            "source_url": n.source_url, "edited_at": n.edited_at or None}


@app.get("/deals/{name}/notes")
def deal_notes_list(name: str, db: Db, who: Who):
    _visible_deal_or_404(db, who, name)
    rows = db.query(DealNote).filter_by(tenant_id=who.tenant, deal=name).order_by(DealNote.id).all()
    return [_note_out(r) for r in rows]


@app.post("/deals/{name}/notes", status_code=201)
def deal_notes_add(name: str, body: DealNoteIn, db: Db, who: Writer):
    _visible_deal_or_404(db, who, name)
    _require(who, "write", "add a note", deal=name)
    n = DealNote(tenant_id=who.tenant, deal=name, author=actor(who), body=body.body.strip(), created_at=_now_iso())
    db.add(n)
    db.commit()
    log_event(db, who.tenant, actor(who), "deal.note", {"deal": name, "id": n.id})
    return _note_out(n)


class PeerSetIn(BaseModel):
    target_id: int
    name: str = Field(min_length=1, max_length=120)


@app.get("/deals/{name}/peer-sets")
def peer_sets_list(name: str, db: Db, who: Who):
    _visible_deal_or_404(db, who, name)
    rows = db.query(PeerSet).filter_by(tenant_id=who.tenant, deal=name).order_by(PeerSet.id).all()
    return [peer_sets_mod.out(r) for r in rows]


@app.post("/deals/{name}/peer-sets", status_code=201)
def peer_sets_save(name: str, body: PeerSetIn, db: Db, who: Writer):
    """Save the comps peers for one target under this deal. Needs the target's SIC code and stated revenue."""
    _visible_deal_or_404(db, who, name)
    _require(who, "write", "save a peer set", deal=name)
    t = db.get(Target, body.target_id)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    if not t.sic or t.revenue is None:
        raise HTTPException(422, "a peer set needs the target's SIC code and stated revenue")
    row = peer_sets_mod.save(db, who.tenant, name, body.name.strip(), t, actor(who))
    log_event(db, who.tenant, actor(who), "peer_set.save", {"deal": name, "id": row.id, "target": t.id})
    return peer_sets_mod.out(row)


@app.post("/deals/{name}/peer-sets/{sid}/refresh")
def peer_sets_refresh(name: str, sid: int, db: Db, who: Writer):
    """Re-read each stored peer's revenue from EDGAR now. The `peer_refresh` workflow does the same on schedule."""
    _visible_deal_or_404(db, who, name)
    _require(who, "write", "refresh a peer set", deal=name)
    row = db.get(PeerSet, sid)
    if row is None or row.tenant_id != who.tenant or row.deal != name:
        raise HTTPException(404, "peer set not found")
    peer_sets_mod.refresh_stored(db, who.tenant, sid)
    log_event(db, who.tenant, actor(who), "peer_set.refresh", {"deal": name, "id": sid})
    db.refresh(row)
    return peer_sets_mod.out(row)


@app.patch("/deals/{name}/notes/{nid}")
def deal_note_edit(name: str, nid: int, body: DealNoteIn, db: Db, who: Writer):
    """Edit a deal note. Its author edits their own; a whole-tenant key may edit any note on the deal. The old
    text is kept in the audit chain (`deal.note_edit`), so an edit never silently replaces the record."""
    _visible_deal_or_404(db, who, name)
    _require(who, "write", "edit a note", deal=name)
    n = db.get(DealNote, nid)
    if n is None or n.tenant_id != who.tenant or n.deal != name:
        raise HTTPException(404, "note not found")
    if n.author != actor(who) and who.restricted:
        raise HTTPException(403, "only the note's author or a whole-tenant key can edit it")
    old = n.body
    n.body = body.body.strip()
    n.edited_at = _now_iso()
    db.commit()
    log_event(db, who.tenant, actor(who), "deal.note_edit", {"deal": name, "id": nid, "before": old, "after": n.body})
    return _note_out(n)


class TargetNoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


def _target_or_404(db: Session, who: Principal, tid: int) -> Target:
    """A target the key may see: same tenant, and not the same company as an MNPI deal the key may not see."""
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant or mnpi_name_conflict(db, who, t.name):
        raise HTTPException(404, "target not found")
    return t


def _target_note_out(n: TargetNote) -> dict:
    return {"id": n.id, "target_id": n.target_id, "author": n.author, "body": n.body,
            "created_at": n.created_at, "edited_at": n.edited_at or None}


@app.get("/targets/{tid}/notes")
def target_notes_list(tid: int, db: Db, who: Who):
    _target_or_404(db, who, tid)
    rows = db.query(TargetNote).filter_by(tenant_id=who.tenant, target_id=tid).order_by(TargetNote.id).all()
    return [_target_note_out(r) for r in rows]


@app.post("/targets/{tid}/notes", status_code=201)
def target_notes_add(tid: int, body: TargetNoteIn, db: Db, who: Writer):
    _target_or_404(db, who, tid)
    n = TargetNote(tenant_id=who.tenant, target_id=tid, author=actor(who), body=body.body.strip(),
                   created_at=_now_iso(), edited_at="")
    db.add(n)
    db.commit()
    log_event(db, who.tenant, actor(who), "target.note", {"target": tid, "id": n.id})
    return _target_note_out(n)


@app.patch("/targets/{tid}/notes/{nid}")
def target_note_edit(tid: int, nid: int, body: TargetNoteIn, db: Db, who: Writer):
    """Same rule as deal notes: the author edits their own; a whole-tenant key may edit any. Old text is audited."""
    _target_or_404(db, who, tid)
    n = db.get(TargetNote, nid)
    if n is None or n.tenant_id != who.tenant or n.target_id != tid:
        raise HTTPException(404, "note not found")
    if n.author != actor(who) and who.restricted:
        raise HTTPException(403, "only the note's author or a whole-tenant key can edit it")
    old = n.body
    n.body = body.body.strip()
    n.edited_at = _now_iso()
    db.commit()
    log_event(db, who.tenant, actor(who), "target.note_edit", {"target": tid, "id": nid, "before": old, "after": n.body})
    return _target_note_out(n)


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
    retag_after_alias = False
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
    if body.sic is not None:
        _require(who, "write", "edit deal sector", deal=name)
        d.sic = body.sic.strip() or None
    if body.sponsor is not None:
        _require(who, "write", "edit deal sponsor", deal=name)
        d.sponsor = body.sponsor.strip() or None
    if body.aliases is not None or body.cik is not None or body.lei is not None:
        _require(who, "write", "edit deal identifiers", deal=name)
        if body.aliases is not None:
            d.aliases = _aliases_text(body.aliases)
            retag_after_alias = True
        if body.cik is not None:
            d.cik = _cik(body.cik)
        if body.lei is not None:
            d.lei = _lei(body.lei)
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
    if retag_after_alias:
        retag_deals(db, who.tenant)  # a new alias can claim meetings already stored
    log_event(db, who.tenant, actor(who), "deal.update", {"name": name, "stage": d.stage, "legal_hold": d.legal_hold})
    return _deal_out(db, who, d)


def _requester(p: Principal) -> str:
    """Who asked for an action, for the four-eyes check: the key, or the person behind an SSO login."""
    return f"key:{p.key_id}" if p.key_id else f"user:{p.identity or ''}"


def _deletable_deal(db: Session, who: Principal, name: str, capability: str = "purge") -> Deal:
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=name).first()
    if d is None or not _dd_scope_ok(who, name) or deal_hidden(d, who):
        raise HTTPException(404, "deal not found")
    _require(who, capability, "delete deals", deal=name)
    if d.legal_hold:
        raise HTTPException(409, "deal is under legal hold; lift the hold before deleting")
    if db.query(Document).filter_by(tenant_id=who.tenant, deal=name).first():
        raise HTTPException(409, "documents still linked to this deal; unlink them first")
    return d


@app.post("/deals/{name}/deletion-request", status_code=201)
def deal_deletion_request(name: str, db: Db, who: Writer):
    """Step one of deleting a deal: an admin asks for it. Nothing is removed until DELETE /deals/{name}."""
    _deletable_deal(db, who, name)
    if db.query(DealDeletion).filter_by(tenant_id=who.tenant, deal=name).first():
        raise HTTPException(409, "deletion already requested for this deal")
    req = DealDeletion(tenant_id=who.tenant, deal=name, requested_by=_requester(who), requested_at=_now_iso())
    db.add(req)
    db.commit()
    log_event(db, who.tenant, actor(who), "deal.delete_requested", {"name": name})
    return {"deal": name, "requested_by": req.requested_by, "requested_at": req.requested_at}


@app.delete("/deals/{name}")
def deal_delete(name: str, db: Db, who: Writer):
    """Step two: confirm the deletion that was requested. Holds and linked documents are refused rather than
    cascaded: deleting evidence the team still relies on is the one step here that cannot be walked back."""
    d = _deletable_deal(db, who, name)
    req = db.query(DealDeletion).filter_by(tenant_id=who.tenant, deal=name).first()
    if req is None:
        raise HTTPException(409, "request the deletion first: POST /deals/{name}/deletion-request")
    if _requester(who) in (req.requested_by, "key:", "user:"):
        raise HTTPException(403, "a different admin key must confirm a deletion someone else requested")
    removed = db.query(DDRequest).filter_by(tenant_id=who.tenant, deal=name).delete()
    requested_by = req.requested_by
    db.query(DealDeletion).filter_by(tenant_id=who.tenant, deal=name).delete()
    db.delete(d)
    db.commit()
    retag_deals(db, who.tenant)  # meetings tagged to the deal lose the tag and their note
    log_event(db, who.tenant, actor(who), "deal.delete",
              {"name": name, "dd_requests_removed": removed, "requested_by": requested_by})
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


def _memo_comps(db: Session, who, entity: str, peers: str, period: str) -> dict | None:
    """Optional comps section: peers (comma-separated entity names) at a period, EV / revenue. None when not asked."""
    names = [n.strip() for n in peers.split(",") if n.strip()]
    if not names or not period:
        return None
    if len(names) > 50:
        raise HTTPException(422, "too many peers")
    return comps_mod.run(db, who.tenant, entity, names, period, ["revenue"], visible_doc_ids(db, who))


def _memo_legal(db: Session, who, legal_doc: str) -> list[dict] | None:
    """Legal red flags for the memo's legal section, from one contract the caller can see (rules only, cited)."""
    if not legal_doc:
        return None
    doc = _own_doc(db, who, legal_doc)
    pages = [(p.number, p.text) for p in db.query(PageRow).filter_by(document_id=doc.id).order_by(PageRow.number)]
    if not pages:
        pages = [(u.idx + 1, u.text) for u in db.query(HtmlUnit).filter_by(document_id=doc.id).order_by(HtmlUnit.idx)]
    doc_type = flagship_mod.detect_doc_type(pages)
    if not doc_type:
        raise HTTPException(400, "legal_doc is not a recognised nda, spa, credit, lease or employment document")
    flags = legal_mod.red_flags(legal_mod.extract(pages, doc_type))
    for f in flags:
        f.setdefault("document_id", doc.id)
    return flags


@app.get("/memo")
def memo(entity: str, db: Db, who: Who, peers: str = "", period: str = "", legal_doc: str = ""):
    comps = _memo_comps(db, who, entity, peers, period)
    legal = _memo_legal(db, who, legal_doc)
    return {"entity": entity, "markdown": build_memo(db, who.tenant, entity, visible_doc_ids(db, who), comps, legal)}


class MemoTemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    sections: list[str] = Field(min_length=1, max_length=8)
    headings: dict[str, str] = Field(default_factory=dict)  # firm heading text per section key
    intro: str = Field(default="", max_length=mt_mod.INTRO_MAX)


@app.get("/memo/templates")
def memo_templates_list(db: Db, who: Who):
    text = mt_mod.list_text(db, who.tenant)
    return {"items": [{"name": k, "sections": v, "built_in": k in TEMPLATES,
                       "headings": text.get(k, {}).get("headings", {}), "intro": text.get(k, {}).get("intro", "")}
                      for k, v in mt_mod.list_templates(db, who.tenant).items()]}


@app.post("/memo/templates", status_code=201)
def memo_templates_save(body: MemoTemplateIn, db: Db, who: Writer):
    """The firm's own memo layout. Tenant-wide, so only a whole-tenant key may save one; a built-in name is refused."""
    if who.restricted:
        raise HTTPException(403, "memo templates are firm-wide; use an unrestricted key")
    if body.name in TEMPLATES or not mt_mod.NAME.match(body.name):
        raise HTTPException(422, "name must be 2-64 lowercase letters, digits, - or _, and not a built-in name")
    try:
        keys = mt_mod.validate_sections(body.sections)
        headings, intro = mt_mod.validate_text(body.headings, body.intro, keys)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    row = db.query(MemoTemplate).filter_by(tenant_id=who.tenant, name=body.name).one_or_none()
    if row is None:
        row = MemoTemplate(tenant_id=who.tenant, name=body.name, created_by=actor(who), created_at=_now_iso())
        db.add(row)
    row.sections = json.dumps(keys)
    row.headings = json.dumps(headings)
    row.intro = intro
    db.commit()
    log_event(db, who.tenant, actor(who), "memo.template_saved", {"name": body.name, "sections": keys})
    return {"name": row.name, "sections": keys, "headings": headings, "intro": intro}


@app.get("/memo/sections")
def memo_sections(entity: str, db: Db, who: Who, template: str = "ic"):
    """Memo with the sections a named template selects, in its order. Unknown templates are refused."""
    try:
        mt_mod.resolve(db, who.tenant, template)
    except KeyError as e:
        names = sorted(mt_mod.list_templates(db, who.tenant))
        raise HTTPException(422, f"unknown template; choose one of {names}") from e
    return {"entity": entity, "template": template,
            "markdown": build_memo_sections(db, who.tenant, entity, template, visible_doc_ids(db, who))}


class MemoDiffBody(BaseModel):
    entity: str = Field(min_length=1, max_length=200)
    previous: str = Field(min_length=1, max_length=200_000)


@app.post("/memo/diff")
def memo_diff(body: MemoDiffBody, db: Db, who: Who):
    """Current memo draft against the previous text the reviewer sends: lines added and removed, sources kept."""
    current = build_memo(db, who.tenant, body.entity, visible_doc_ids(db, who))
    return {"entity": body.entity, **memo_diff_mod.diff_memos(body.previous, current)}


def _whole_tenant(who: Principal) -> None:
    # A saved memo keeps the figures the builder saw; a narrower key would store, or read, text it cannot see.
    if who.restricted:
        raise HTTPException(403, "memo versions cover the whole tenant; use an unrestricted key")


class MemoCommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@app.post("/memo/versions", status_code=201)
def memo_version_save(entity: Annotated[str, Query(min_length=1, max_length=200)], db: Db, who: Writer):
    """Save the current memo draft as the next version of this entity."""
    _whole_tenant(who)
    text = build_memo(db, who.tenant, entity, visible_doc_ids(db, who))
    last = db.query(func.max(MemoVersion.number)).filter_by(tenant_id=who.tenant, entity=entity).scalar() or 0
    v = MemoVersion(tenant_id=who.tenant, entity=entity, number=last + 1, markdown=text, created_by=actor(who),
                    created_at=datetime.now(UTC).isoformat(timespec="seconds"))
    db.add(v)
    db.commit()
    return {"id": v.id, "entity": entity, "number": v.number}


@app.get("/memo/versions")
def memo_versions(entity: str, db: Db, who: Who):
    _whole_tenant(who)
    rows = db.query(MemoVersion).filter_by(tenant_id=who.tenant, entity=entity).order_by(MemoVersion.number).all()
    return {"items": [{"id": v.id, "number": v.number, "created_by": v.created_by, "created_at": v.created_at}
                      for v in rows]}


@app.get("/memo/versions/diff")
def memo_versions_diff(from_id: int, to_id: int, db: Db, who: Who):
    """Lines added and removed between two saved versions of the same entity."""
    _whole_tenant(who)
    a, b = db.get(MemoVersion, from_id), db.get(MemoVersion, to_id)
    if a is None or b is None or a.tenant_id != who.tenant or b.tenant_id != who.tenant or a.entity != b.entity:
        raise HTTPException(404, "version not found")
    return {"entity": a.entity, "from": a.number, "to": b.number,
            **memo_diff_mod.diff_memos(a.markdown, b.markdown)}


@app.get("/memo/versions/{version_id}")
def memo_version_get(version_id: int, db: Db, who: Who):
    _whole_tenant(who)
    v = db.get(MemoVersion, version_id)
    if v is None or v.tenant_id != who.tenant:
        raise HTTPException(404, "version not found")
    comments = db.query(MemoComment).filter_by(tenant_id=who.tenant, version_id=v.id).order_by(MemoComment.id).all()
    return {"id": v.id, "entity": v.entity, "number": v.number, "markdown": v.markdown, "created_by": v.created_by,
            "created_at": v.created_at,
            "comments": [{"id": c.id, "author": c.author, "body": c.body, "created_at": c.created_at} for c in comments]}


@app.post("/memo/versions/{version_id}/comments", status_code=201)
def memo_version_comment(version_id: int, body: MemoCommentBody, db: Db, who: Writer):
    _whole_tenant(who)
    v = db.get(MemoVersion, version_id)
    if v is None or v.tenant_id != who.tenant:
        raise HTTPException(404, "version not found")
    c = MemoComment(tenant_id=who.tenant, version_id=v.id, author=actor(who), body=body.body,
                    created_at=datetime.now(UTC).isoformat(timespec="seconds"))
    db.add(c)
    db.commit()
    return {"id": c.id}


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


@app.get("/market/quote")
def market_quote(symbol: str, provider: str, who: Who, fetch: Annotated[Callable, Depends(get_market_fetch)],
                 currency: str | None = None):
    """Latest price from a named provider: yahoo, stooq (needs `currency`), factset (needs credentials),
    ecb (EUR per unit of symbol, e.g. USD) or fred (a series id such as DGS10; needs FRED_API_KEY).
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
        elif provider == "ecb":
            from app.macrodata import EcbFxProvider
            p = EcbFxProvider(fetch)
        elif provider == "fred":
            from app.macrodata import FredProvider
            p = FredProvider(os.environ.get("FRED_API_KEY", ""), fetch=fetch)  # keyless CSV when unset
        else:
            raise HTTPException(422, "provider must be yahoo, stooq, factset, ecb or fred")
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


class EmailAttachIn(BaseModel):
    deal: str = Field(min_length=1, max_length=128)


@app.get("/deals/{name}/meetings")
def deal_meetings(name: str, db: Db, who: Who):
    """Calendar meetings whose title names this deal or one of its aliases, soonest first. A deal the key cannot
    see, or an MNPI deal the key is not cleared for, answers 404 as if it did not exist."""
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=name).first()
    if d is None or deal_hidden(d, who) or (who.deals is not None and name not in who.deals):
        raise HTTPException(404, "no such deal")
    rows = db.query(CalendarEvent).filter_by(tenant_id=who.tenant, deal=name).order_by(CalendarEvent.starts_at).all()
    return {"meetings": [{"title": r.title, "starts_at": r.starts_at, "url": r.url, "board": r.board,
                          "source": r.source} for r in rows]}


@app.get("/email/review")
def email_review(db: Db, who: Who):
    """Ingested emails no deal matched, waiting for someone to attach them. Only unscoped keys see them."""
    if who.deals is not None:
        return {"emails": []}
    return {"emails": unattached_emails(db, who.tenant)}


@app.post("/email/review/{doc_id}/attach")
def email_attach(doc_id: str, body: EmailAttachIn, db: Db, who: Writer):
    """Attach one unattached email to a deal by hand. The deal must be one this key may write to, and not an MNPI
    deal the key cannot see."""
    _require(who, "write", "attach an email to a deal", deal=body.deal)
    if who.deals is not None and body.deal not in who.deals:
        raise HTTPException(403, "this key is not scoped to that deal")
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=body.deal).first()
    if d is None or deal_hidden(d, who):
        raise HTTPException(404, "no such deal")
    doc = db.query(Document).filter_by(tenant_id=who.tenant, id=doc_id).first()
    is_email = db.query(DocumentSource).filter(DocumentSource.document_id == doc_id,
                                               DocumentSource.connector.in_(EMAIL_CONNECTORS)).first()
    if doc is None or doc.deal is not None or is_email is None:
        raise HTTPException(404, "no unattached email with that id")
    doc.deal = body.deal
    log_event(db, who.tenant, actor(who), "email.attach", {"doc_id": doc_id, "deal": body.deal})
    db.commit()
    return {"document_id": doc_id, "deal": body.deal}


@app.get("/facts.xlsx")
def facts_xlsx(db: Db, who: Who, entity: str | None = None):
    """Verified and reviewed facts as a workbook; each value cell's comment lists its sources."""
    log_event(db, who.tenant, actor(who), "facts.export", {"entity": entity, "format": "xlsx"})
    data = build_facts_xlsx(db, who.tenant, entity, visible_doc_ids(db, who))
    if outbound.pii_on(db, who.tenant):
        data = outbound.xlsx(data)
    return Response(data, headers={"Content-Disposition": 'attachment; filename="facts.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class CiteIn(BaseModel):
    value: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=512)
    url: str | None = Field(default=None, max_length=1024)

    def cite(self) -> lp_mod.Cite:
        return lp_mod.Cite(self.value, self.source, self.url)


class FlowIn(BaseModel):
    on: DateT
    amount: Decimal
    source: CiteIn


class KpiIn(BaseModel):
    company: str = Field(max_length=256)
    metric: str = Field(max_length=128)
    period: str = Field(max_length=64)
    value: CiteIn


class LpLetterIn(BaseModel):
    fund: str = Field(max_length=256)
    as_of: DateT
    flows: list[FlowIn] = Field(min_length=1, max_length=500)
    nav: CiteIn
    kpis: list[KpiIn] = Field(default_factory=list, max_length=200)
    tone: CiteIn | None = None


class CapitalCallIn(BaseModel):
    fund: str = Field(max_length=256)
    amount: CiteIn
    purpose: str = Field(max_length=512)
    due: DateT
    notice_days: CiteIn
    commitments: dict[str, CiteIn] = Field(min_length=1, max_length=500)
    kind: str = Field(default="capital call", max_length=40)
    lp: str | None = Field(default=None, max_length=256)


def _outbound(db: Session, who: Principal, kind: str, data: bytes) -> bytes:
    """A file about to leave the system (download or attachment): identifiers stripped when the tenant's PII
    flag is on. `kind` is the file type: docx, pptx or xlsx."""
    if not outbound.pii_on(db, who.tenant):
        return data
    return {"docx": outbound.docx, "pptx": outbound.pptx, "xlsx": outbound.xlsx}[kind](data)


def _lp_output(model: lp_mod.Model, fmt: str, name: str, style: dict | None = None, pii: bool = False):
    if fmt == "json":
        return {**model.to_dict(), **({"style": style} if style is not None else {})}
    if fmt == "docx":
        data = lp_mod.to_docx(model)
        return Response(outbound.docx(data) if pii else data,
                        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'},
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if fmt == "pptx":
        data = lp_mod.to_pptx(model)
        return Response(outbound.pptx(data) if pii else data,
                        headers={"Content-Disposition": f'attachment; filename="{name}.pptx"'},
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    raise HTTPException(422, "format must be json, docx or pptx")


class DdqQuestionIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    section: str = Field(default="", max_length=128)
    text: str = Field(min_length=3, max_length=1000)


class DdqIn(BaseModel):
    questions: list[DdqQuestionIn] = Field(min_length=1, max_length=300)


@app.post("/ddq/answer")
def ddq_answer(body: DdqIn, who: Who, db: Db):
    """Answers a DDQ only where an accepted firm rule matches each question; the rest are listed as unanswered.
    Rules whose source document the caller cannot see are not used."""
    visible = visible_doc_ids(db, who)
    accepted = {k: [r for r in rows if visible is None or r["source"]["document_id"] in visible]
                for k, rows in fk.profile(db, who.tenant).items()}
    qs = [ddq_mod.Question(q.id, q.section, q.text) for q in body.questions]
    try:  # retrieval plus the configured local model; word overlap when no model is set up
        out = ddq_llm_mod.answer(qs, accepted, get_llm(db, who.tenant))
    except NoLLMConfigured:
        out = ddq_mod.answer(qs, accepted)
    log_event(db, who.tenant, actor(who), "ddq.answer", {"questions": len(qs),
              "answered": sum(1 for r in out if r["status"] == "answered")})
    return {"answers": out, "answered": sum(1 for r in out if r["status"] == "answered"),
            "unanswered": sum(1 for r in out if r["status"] == "unanswered")}
class TermsIn(BaseModel):
    hurdle: Decimal = Field(ge=0, lt=1)
    carry: Decimal = Field(ge=0, lt=1)
    catchup: Decimal = Field(ge=0, le=1)
    source: str = Field(min_length=1, max_length=512)


class WfFlowIn(BaseModel):
    on: DateT
    amount: Decimal = Field(gt=0)
    source: str = Field(min_length=1, max_length=512)


class WfDealIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    contributions: list[WfFlowIn] = Field(default_factory=list, max_length=500)
    distributions: list[WfFlowIn] = Field(default_factory=list, max_length=500)


class EscrowIn(BaseModel):
    pct: Decimal = Field(ge=0, lt=1)
    days: int = Field(ge=0, le=3650)
    source: str = Field(min_length=1, max_length=512)


class WaterfallIn(BaseModel):
    mode: str = Field(default="european", pattern="^(european|american)$")
    terms: TermsIn
    escrow: EscrowIn | None = None  # american only: holdback on each deal distribution
    clawback: bool = False  # american only: GP returns carry above carry owed on total fund profit
    contributions: list[WfFlowIn] = Field(default_factory=list, max_length=500)
    distributions: list[WfFlowIn] = Field(default_factory=list, max_length=500)
    deals: list[WfDealIn] = Field(default_factory=list, max_length=200)
    commitments: dict[str, CiteIn] = Field(default_factory=dict, max_length=500)


def _wf_flows(items: list[WfFlowIn]) -> list[wf_lp_mod.Flow]:
    return [wf_lp_mod.Flow(i.on, i.amount, i.source) for i in items]


def _tiers_dict(t: wf_lp_mod.Tiers) -> dict[str, str]:
    return {k: str(getattr(t, k)) for k in t.__dataclass_fields__}


@app.post("/waterfall/lp")
def waterfall_lp(body: WaterfallIn, who: Writer, db: Db):
    """Distribution waterfall: return of capital, preferred return, GP catch-up, carry. European runs the whole
    fund; american runs each deal on its own (no clawback). Terms and each flow carry their source."""
    try:
        terms = wf_lp_mod.Terms(body.terms.hurdle, body.terms.carry, body.terms.catchup, body.terms.source)
        if body.mode == "european":
            if not body.distributions:
                raise ValueError("at least one distribution is needed")
            r = wf_lp_mod.run(_wf_flows(body.contributions), _wf_flows(body.distributions), terms)
            res = {"mode": "european", "totals": _tiers_dict(r.totals),
                   "steps": [{"on": s.on.isoformat(), "amount": str(s.amount), "source": s.source,
                              "tiers": _tiers_dict(s.tiers)} for s in r.steps]}
            lp_totals = r.totals
        else:
            if not body.deals:
                raise ValueError("american needs deals")
            deals = {}
            for d in body.deals:
                dists = _wf_flows(d.distributions)
                if body.escrow:
                    dists, later = wf_lp_mod.hold_back(dists, wf_lp_mod.Escrow(
                        body.escrow.pct, body.escrow.days, body.escrow.source))
                    dists = dists + later
                deals[d.name] = (_wf_flows(d.contributions), dists)
            results = wf_lp_mod.american(deals, terms)
            lp_totals = wf_lp_mod.Tiers()
            for r in results.values():
                lp_totals.add(r.totals)
            res = {"mode": "american", "totals": _tiers_dict(lp_totals),
                   "deals": {n: {"totals": _tiers_dict(r.totals)} for n, r in results.items()}}
            if body.clawback:
                all_c = [f for d in body.deals for f in _wf_flows(d.contributions)]
                all_d = [f for d in body.deals for f in _wf_flows(d.distributions)]
                cb = wf_lp_mod.clawback(all_c, all_d, results, terms)
                res["clawback"] = {"gp_received": str(cb.gp_received), "gp_owed": str(cb.target),
                                   "returned_to_lps": str(cb.amount)}
                lp_totals.to_lp_split += cb.amount  # returned to LPs; the GP gives it back
                res["lp_total_after_clawback"] = str(lp_totals.lp())
        if body.commitments:
            amounts = {k: Decimal(v.value.replace(",", "")) for k, v in body.commitments.items()}
            shares = wf_lp_mod.per_lp(lp_totals, amounts)
            res["per_lp"] = {k: {"lp_proceeds": str(v), "commitment": body.commitments[k].value,
                                 "source": body.commitments[k].source} for k, v in shares.items()}
    except (ValueError, ArithmeticError) as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "waterfall.lp", {"mode": body.mode})
    return res


@app.post("/lp/letter")
def lp_letter(body: LpLetterIn, who: Writer, db: Db, format: str = "json", style: bool = False):
    """Quarterly LP letter: fund metrics from dated flows, portfolio KPIs and the accepted LP tone rule.
    Every figure is cited to the source supplied with it. format: json, docx or pptx.
    style=true lets the configured local model rephrase the narrative in the tone rule; numbers are masked
    and the rewrite is kept only if it passes the number check (json shows the outcome under "style")."""
    try:
        model = lp_mod.lp_letter(body.fund, body.as_of,
                                 [lp_mod.Flow(f.on, f.amount, f.source.cite()) for f in body.flows],
                                 body.nav.cite(),
                                 [lp_mod.Kpi(k.company, k.metric, k.period, k.value.cite()) for k in body.kpis],
                                 body.tone.cite() if body.tone else None)
    except (ValueError, ArithmeticError) as e:
        raise HTTPException(422, str(e)) from e
    outcome = None
    if style:
        if body.tone is None:
            outcome = {"status": "not_requested", "reason": "no accepted LP tone rule"}
        else:
            try:
                model, st = lp_tone_mod.rewrite(model, body.tone.value, get_llm(db, who.tenant))
                outcome = {"status": st.status, "reason": st.reason}
            except NoLLMConfigured:
                outcome = {"status": "not_requested", "reason": "no local model configured"}
    log_event(db, who.tenant, actor(who), "lp.letter", {"fund": body.fund, "format": format})
    return _lp_output(model, format, "lp-letter", outcome, pii=outbound.pii_on(db, who.tenant))


@app.post("/lp/capital-call")
def lp_capital_call(body: CapitalCallIn, who: Writer, db: Db, format: str = "json"):
    """Capital call or distribution notice: each LP's pro-rata share, every commitment and the notice period
    cited to its source. lp=name gives one LP's notice; omitted gives the summary for all LPs."""
    try:
        model = lp_mod.capital_call_notice(body.fund, body.amount.cite(), body.purpose, body.due,
                                           body.notice_days.cite(),
                                           {k: v.cite() for k, v in body.commitments.items()},
                                           body.kind, body.lp)
    except (ValueError, ArithmeticError) as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "lp.capital_call", {"fund": body.fund, "format": format})
    return _lp_output(model, format, "capital-call", pii=outbound.pii_on(db, who.tenant))


@app.get("/memo.docx")
def memo_docx(entity: str, db: Db, who: Who, peers: str = "", period: str = "", legal_doc: str = ""):
    log_event(db, who.tenant, actor(who), "memo.export", {"entity": entity, "format": "docx"})
    comps = _memo_comps(db, who, entity, peers, period)
    legal = _memo_legal(db, who, legal_doc)
    return Response(_outbound(db, who, "docx", build_memo_docx(db, who.tenant, entity, visible_doc_ids(db, who), comps, legal)), headers={
        "Content-Disposition": 'attachment; filename="memo.docx"'},
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class FlagshipIn(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)
    entity: str = Field(min_length=1, max_length=256)
    legal_doc_type: str | None = Field(default=None, pattern="^(nda|spa|credit)$")
    lbo: dict = Field(default_factory=dict)  # {"inputs": {name: {value, source} | {value, assumption}}, ...}
    extract: bool = False  # read the filing's inline XBRL tags into verified facts (no LLM)
    sic: str | None = Field(default=None, max_length=8)  # the entity's SIC code, for peers
    cik: str | None = Field(default=None, max_length=12)  # the entity's own CIK, left out of its peers
    peers_pages: int = Field(default=1, ge=1, le=10)
    precedents: dict | None = None  # {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "limit": 5}


def _peer_ev(db: Session, tenant_id: str, name: str, scope: set[str] | None):
    """The latest verified enterprise_value fact for a peer that this caller may see, from a market-data feed or a
    filing. A fact cited to a document outside the caller's scope is skipped, as comps skip it."""
    rows = (db.query(Fact).filter_by(tenant_id=tenant_id, entity=name, metric=EV_METRIC, status="verified")
            .order_by(Fact.id.desc()).all())
    f = next((f for f in rows if fact_visible(f, scope)), None)
    if f is None:
        return None
    doc = db.get(Document, f.sources[0].document_id)  # the feed record: its file name carries the feed's label
    return SimpleNamespace(id=f.id, value=f.value, unit=f.unit, label=doc.filename if doc else None)


@app.post("/flagship/run")
def flagship_run(body: FlagshipIn, who: Who, db: Db):
    """One run over an uploaded document. Steps: intake, extraction (the filing's own tags, cited), comps (SIC peers by
    size), precedents (merger 8-Ks in a window), legal red flags, LBO returns and the IC memo deck. Each step reports
    ok, skipped or failed with its reason; the memo is downloaded from /memo.pptx?entity=..."""
    doc = _own_doc(db, who, body.document_id)
    pages = [(p.number, p.text) for p in db.query(PageRow).filter_by(document_id=doc.id).order_by(PageRow.number)]
    if not pages:  # an HTML exhibit is stored as text blocks, not pages; each block numbers as one page
        pages = [(u.idx + 1, u.text) for u in db.query(HtmlUnit).filter_by(document_id=doc.id).order_by(HtmlUnit.idx)]
    steps = [flagship_mod.Step("intake", "ok", result={"document": doc.filename, "pages": len(pages)})]
    if body.extract:
        blob = db.get(DocumentFile, doc.id)
        steps.append(flagship_mod.extraction_step(db, who.tenant, doc.id, body.entity, blob.data) if blob
                     else flagship_mod.Step("extraction", "failed", "original file not stored"))
    else:
        steps.append(flagship_mod.Step("extraction", "skipped", "set extract=true to read the filing's tags"))
    rev_fact = db.query(Fact).filter_by(tenant_id=who.tenant, entity=body.entity, metric="revenue",
                                        status="verified").order_by(Fact.id.desc()).first()
    revenue = rev_fact.value if rev_fact else None
    exclude = {body.cik.zfill(10)} if body.cik else set()
    # Without a SEC contact the EDGAR-backed steps cannot run at all. That is a skip with the reason, not a failure.
    no_sec_contact = not os.environ.get("SEC_USER_AGENT")
    scope = visible_doc_ids(db, who)
    if no_sec_contact:
        steps.append(flagship_mod.Step("comps", "skipped", "SEC_USER_AGENT not set: SIC peers come from EDGAR"))
    else:
        try:
            steps.append(flagship_mod.comps_step(revenue, body.sic, exclude, body.peers_pages, peers_mod.discover,
                                                 ev_lookup=lambda name: _peer_ev(db, who.tenant, name, scope)))
        except (OSError, ValueError, RuntimeError) as e:
            steps.append(flagship_mod.Step("comps", "failed", f"{type(e).__name__}: {e}"))
    if no_sec_contact and body.precedents:
        steps.append(flagship_mod.Step("precedents", "skipped", "SEC_USER_AGENT not set: merger 8-Ks come from EDGAR"))
    else:
        try:
            steps.append(flagship_mod.precedents_step(body.precedents, pfetch_mod.build))
        except (OSError, ValueError, RuntimeError) as e:
            steps.append(flagship_mod.Step("precedents", "failed", f"{type(e).__name__}: {e}"))
    legal_type = body.legal_doc_type or flagship_mod.detect_doc_type(pages)
    try:
        reader = get_llm(db, who.tenant) if legal_type else None
    except NoLLMConfigured:
        reader = None
    steps.append(flagship_mod.legal_step(pages, doc.id, legal_type, legal_mod, reader))
    ext_step = next((s for s in steps if s.name == "extraction"), None)
    if not body.extract:
        steps.append(flagship_mod.Step("crosscheck", "skipped", "set extract=true to cross-check its figures"))
    elif no_sec_contact:
        steps.append(flagship_mod.Step("crosscheck", "skipped", "SEC_USER_AGENT not set: companyfacts needs a contact"))
    else:
        steps.append(flagship_mod.crosscheck_step(ext_step, body.cik, None))
    lbo_raw = dict(body.lbo.get("inputs") or {})
    if "ebitda" not in lbo_raw:
        derived = flagship_mod.derive_ebitda(steps, doc.id, doc.filename)
        if derived:
            lbo_raw["ebitda"] = derived
    steps.append(flagship_mod.lbo_step(lbo_raw, doc.id))
    verified = db.query(Fact).filter_by(tenant_id=who.tenant, entity=body.entity, status="verified").count()
    if verified:
        steps.append(flagship_mod.Step("memo", "ok", result={
            "verified_facts": verified, "download": f"/memo.pptx?entity={body.entity}"}))
    else:
        steps.append(flagship_mod.Step("memo", "skipped", f"no verified facts for {body.entity} yet"))
    log_event(db, who.tenant, actor(who), "flagship.run", {"document_id": doc.id, "entity": body.entity})
    return {"document_id": doc.id, "steps": [s.to_dict() for s in steps]}


@app.get("/memo.pptx")
def memo_pptx(entity: str, db: Db, who: Who, legal_doc: str = ""):
    log_event(db, who.tenant, actor(who), "memo.export", {"entity": entity, "format": "pptx"})
    return Response(_outbound(db, who, "pptx", build_memo_pptx(db, who.tenant, entity, visible_doc_ids(db, who), _memo_legal(db, who, legal_doc))), headers={
        "Content-Disposition": 'attachment; filename="memo.pptx"'},
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=2, max_length=500)


@app.post("/search/saved", status_code=201)
def saved_search_save(body: SavedSearchIn, db: Db, who: Writer):
    """Save a named search. Saving under an existing name replaces its query."""
    row = db.query(SavedSearch).filter_by(tenant_id=who.tenant, name=body.name).one_or_none()
    if row is None:
        row = SavedSearch(tenant_id=who.tenant, name=body.name, created_by=actor(who),
                          created_at=datetime.now(UTC).isoformat(timespec="seconds"))
        db.add(row)
    row.query = body.query
    db.commit()
    return {"id": row.id, "name": row.name, "query": row.query}


@app.get("/search/saved")
def saved_search_list(db: Db, who: Who):
    rows = db.query(SavedSearch).filter_by(tenant_id=who.tenant).order_by(SavedSearch.name).all()
    return {"items": [{"id": r.id, "name": r.name, "query": r.query} for r in rows]}


@app.get("/search/saved/{search_id}/run")
def saved_search_run(search_id: int, db: Db, who: Who, k: int = Query(5, ge=1, le=20)):
    """Rerun a saved search through the normal search path, so tenant, deal and document filters apply to the rerunner."""
    row = db.get(SavedSearch, search_id)
    if row is None or row.tenant_id != who.tenant:
        raise HTTPException(404, "saved search not found")
    return {"search": row.name, "items": search(row.query, db, who, None, k)}


@app.get("/search/notes")
def search_notes(q: str, db: Db, who: Who, limit: int = Query(50, ge=1, le=200)):
    """Shared deal notes that contain the words in q. Deal visibility and MNPI hiding apply before matching."""
    terms = [t.lower() for t in q.split() if t.strip()]
    if not terms:
        raise HTTPException(422, "query is required")
    scope = deal_scope(db, who)
    rows = db.query(DealNote).filter_by(tenant_id=who.tenant).order_by(DealNote.id.desc()).all()
    hits = [n for n in rows if (scope is None or n.deal in scope)
            and all(t in n.body.lower() for t in terms)]
    return {"query": q, "items": [_note_out(n) for n in hits[:limit]]}


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
    sic: str | None = Field(default=None, max_length=8)
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
def add_observation(company_id: int, fact_id: int, db: Db, who: Writer,
                    kind: Literal["actual", "budget", "mark"] = "actual"):
    tenant = who.tenant
    f = db.get(Fact, fact_id)
    if f is not None and f.tenant_id == tenant and not fact_visible(f, visible_doc_ids(db, who)):
        raise HTTPException(422, "observation requires a verified, cited fact")
    try:
        o = record_observation(db, tenant, company_id, fact_id, kind)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, tenant, actor(who), "kpi.record", {"observation_id": o.id, "fact_id": fact_id, "kind": kind})
    return {"id": o.id, "metric": o.metric, "period": o.period, "value": str(o.value)}


@app.get("/portfolio/companies/{company_id}/kpis")
def kpis(company_id: int, db: Db, who: Who):
    scope = visible_doc_ids(db, who)
    return [{"metric": o.metric, "period": o.period, "value": str(o.value), "unit": o.unit,
             "fact_id": o.fact_id} for o in current_kpis(db, who.tenant, company_id)
            if fact_visible(db.get(Fact, o.fact_id), scope)]


@app.get("/portfolio/companies/{company_id}/budget-vs-actual")
def budget_vs_actual(company_id: int, period: str, db: Db, who: Who):
    """Each metric with an actual or a budget figure for the period, side by side. Both figures are cited. A metric
    where either side cites a document the caller may not see is left out, so no hidden figure shows through the
    other side or the variance."""
    scope = visible_doc_ids(db, who)
    sides: dict[str, dict[str, KpiObservation]] = {}
    for o in current_kpis(db, who.tenant, company_id) + current_kpis(db, who.tenant, company_id, "budget"):
        if o.period == period:
            sides.setdefault(o.metric, {})[o.kind] = o
    rows = []
    for metric in sorted(sides):
        pair = sides[metric]
        act, bud = pair.get("actual"), pair.get("budget")
        if any(not fact_visible(db.get(Fact, o.fact_id), scope) for o in (act, bud) if o is not None):
            continue
        row = {"metric": metric, "unit": (act or bud).unit, "actual": None, "budget": None,
               "variance": None, "variance_pct": None}
        if act is not None:
            row["actual"] = _cited_figure(db, act.fact_id, str(act.value))
        if bud is not None:
            row["budget"] = _cited_figure(db, bud.fact_id, str(bud.value))
        if act is not None and bud is not None:
            diff, pct = budget_variance(act.value, bud.value)
            row["variance"] = str(diff)
            row["variance_pct"] = None if pct is None else str(round(pct, 2))
        rows.append(row)
    return {"period": period, "metrics": rows}


@app.get("/portfolio/companies/{company_id}/roll-forward")
def valuation_roll_forward(company_id: int, period: str, prior: str, db: Db, who: Who,
                           mark_metric: str = Query(MARK_METRIC, max_length=128)):
    """Opening mark (prior period end), closing mark, cash in and out over the period, and the change in value
    that the cash flows leave unexplained. Every figure is cited. A figure the caller may not see reads as missing,
    so the change is withheld rather than computed from a hidden number."""
    scope = visible_doc_ids(db, who)

    def figure(rows, metric: str, p: str):
        o = next((o for o in rows if o.metric == metric and o.period == p), None)
        if o is None or not fact_visible(db.get(Fact, o.fact_id), scope):
            return None, None
        return o.value, _cited_figure(db, o.fact_id, str(o.value))

    marks = current_kpis(db, who.tenant, company_id, "mark")
    actuals = current_kpis(db, who.tenant, company_id)
    open_v, open_c = figure(marks, mark_metric, prior)
    close_v, close_c = figure(marks, mark_metric, period)
    contrib_v, contrib_c = figure(actuals, "contributions", period)
    dist_v, dist_c = figure(actuals, "distributions", period)
    change = roll_forward(open_v, close_v, contrib_v, dist_v)
    return {"period": period, "prior": prior, "opening": open_c, "closing": close_c,
            "contributions": contrib_c, "distributions": dist_c,
            "change_in_value": None if change is None else str(change)}


def _cited_figure(db: Session, fact_id: int, value: str) -> dict:
    """A figure as the portfolio routes return it: the value, its fact, and the document it was read from."""
    c = _fact_cite(db, fact_id, value)
    return {"value": value, "fact_id": fact_id, "source": c.source, "url": c.url}


def _fact_cite(db: Session, fact_id: int, value: str) -> lp_mod.Cite:
    """The cited source of one figure, as the LP model takes it: the document it was read from, and its link."""
    f = db.get(Fact, fact_id)
    src = f.sources[0] if f is not None and f.sources else None
    doc = db.get(Document, src.document_id) if src is not None else None
    link = db.query(DocumentSource).filter_by(document_id=src.document_id).first() if src is not None else None
    return lp_mod.Cite(value, doc.filename if doc else f"fact {fact_id}", link.url if link else None)


@app.get("/portfolio/lp-report")
def portfolio_lp_report(period: str, prior: str, db: Db, who: Writer, format: str = "json"):
    """Per-company section for LP reporting: cited actuals for the period, budget against actual where both are on
    file, and the change in value from the roll-forward. Every line carries its source. A figure the caller may not
    see is left out, as the company routes leave it out."""
    model = lp_mod.Model(f"Portfolio LP report: {period} (prior mark {prior})")
    for c in db.query(PortfolioCompany).filter_by(tenant_id=who.tenant).order_by(PortfolioCompany.name).all():
        model.para((f"{c.name}:", None))
        kpi_rows = kpis(c.id, db, who)
        for k in kpi_rows:
            model.para((f"{k['metric']} {k['value']} {k['unit']} for {period}.",
                        _fact_cite(db, k["fact_id"], k["value"])))
        for m in budget_vs_actual(c.id, period, db, who)["metrics"]:
            if m["actual"] is None or m["budget"] is None:
                continue
            text = (f"{m['metric']}: actual {m['actual']['value']} against budget {m['budget']['value']}, "
                    f"variance {m['variance']}.")
            model.para((text, _fact_cite(db, m["actual"]["fact_id"], m["actual"]["value"])))
        rf = valuation_roll_forward(c.id, period, prior, db, who)
        if rf["change_in_value"] is not None and rf["closing"] is not None:
            text = (f"Change in value from {prior} to {period}: {rf['change_in_value']} "
                    "(closing mark less opening mark, adjusted for cash in and out).")
            model.para((text, _fact_cite(db, rf["closing"]["fact_id"], rf["closing"]["value"])))
        if not kpi_rows:
            model.para((f"No figures on file for {period}.", None))
    return _lp_output(model, format, "portfolio-lp-report", pii=outbound.pii_on(db, who.tenant))


@app.get("/portfolio/submissions")
def kpi_submissions(period: str, db: Db, who: Who):
    """Which portfolio companies have filed any KPI for the period and which have not, so the missing ones can be
    chased. Only observations whose citing document the caller may see count as a submission."""
    scope = visible_doc_ids(db, who)
    submitted, missing = [], []
    for c in db.query(PortfolioCompany).filter_by(tenant_id=who.tenant).order_by(PortfolioCompany.name).all():
        obs = [o for o in current_kpis(db, who.tenant, c.id) if o.period == period
               and fact_visible(db.get(Fact, o.fact_id), scope)]
        row = {"company_id": c.id, "name": c.name, "metrics": sorted({o.metric for o in obs})}
        (submitted if obs else missing).append(row)
    return {"period": period, "submitted": submitted, "missing": missing,
            "pct_submitted": round(100 * len(submitted) / (len(submitted) + len(missing)), 1)
            if submitted or missing else None}


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
            "tests": (tests := evaluate_covenant(db, c, scope)), "compliance": compliance_summary(tests)} for c in covs]
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


@app.post("/valuation-rounds/import", status_code=201)
async def valuation_rounds_import(file: Annotated[UploadFile, File()], db: Db, who: Writer):
    """Import a round/valuation export. Columns: company, round_date, round_type, post_money, currency."""
    if who.deals is not None:
        raise HTTPException(403, "walled keys cannot import valuations")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(422, "file must be UTF-8 text") from e
    rows, errors, missing = parse_rounds(text)
    if missing:
        raise HTTPException(422, f"missing columns: {missing}")
    if not rows:
        raise HTTPException(422, {"detail": "no valid rows", "errors": errors[:50]})
    res = ingest_any(db, who.tenant, data, file.filename or "rounds.csv")
    if not res.documents:
        reason = res.skipped[0]["reason"] if res.skipped else "cannot store file"
        raise HTTPException(409 if "already stored" in reason else 422, reason)
    doc = res.documents[0]
    if db.query(ValuationRound).filter_by(tenant_id=who.tenant, document_id=doc.id).first():
        raise HTTPException(409, "this file was already imported")
    for r in rows:
        db.add(ValuationRound(tenant_id=who.tenant, company=r.company, round_date=r.round_date,
                              round_type=r.round_type, post_money=r.post_money, currency=r.currency,
                              document_id=doc.id, line=r.line))
    db.commit()
    return {"document_id": doc.id, "accepted": len(rows), "rejected": errors}


@app.get("/valuation-rounds")
def valuation_rounds_list(db: Db, who: Who, company: str | None = None):
    """Round history, oldest first. Rows whose source document the caller cannot see are not returned."""
    if who.deals is not None:
        return []
    scope = visible_doc_ids(db, who)
    q = db.query(ValuationRound).filter_by(tenant_id=who.tenant)
    if company:
        q = q.filter_by(company=company)
    return [{"id": v.id, "company": v.company, "round_date": v.round_date, "round_type": v.round_type,
             "post_money": str(v.post_money), "currency": v.currency, "document_id": v.document_id, "line": v.line}
            for v in q.order_by(ValuationRound.round_date, ValuationRound.id) if scope is None or v.document_id in scope]


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
def calc_comps(body: CompsIn, db: Db, who: Who, fetch: Annotated[Callable, Depends(get_market_fetch)]):
    """Trading comps (or precedents: peers are deal entities with enterprise_value facts) and implied range."""
    if len(body.peers) > 200 or len(body.metrics) > 10:
        raise HTTPException(422, "too many peers or metrics")
    from app.macrodata import EcbFxProvider, fx_rate
    fx = (lambda frm, to: fx_rate(EcbFxProvider(fetch), frm, to)) if fetch is not None else None
    return comps_mod.run(db, who.tenant, body.target, body.peers, body.period, body.metrics,
                         visible_doc_ids(db, who), body.target_period, body.ev_period, fx)


@app.post("/calc/comps.docx")
def calc_comps_docx(body: CompsIn, db: Db, who: Who):
    """Word note of the comps result with a source for every input."""
    res = comps_mod.run(db, who.tenant, body.target, body.peers, body.period, body.metrics,
                        visible_doc_ids(db, who), body.target_period, body.ev_period)
    log_event(db, who.tenant, actor(who), "comps.export", {"format": "docx", "target": body.target})
    return Response(_outbound(db, who, "docx", comps_mod.to_docx(db, res)), headers={"Content-Disposition": 'attachment; filename="comps.docx"'},
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/calc/comps.pptx")
def calc_comps_pptx(body: CompsIn, db: Db, who: Who):
    """Slide deck of the comps result; every figure cites its source line."""
    res = comps_mod.run(db, who.tenant, body.target, body.peers, body.period, body.metrics,
                        visible_doc_ids(db, who), body.target_period, body.ev_period)
    log_event(db, who.tenant, actor(who), "comps.export", {"format": "pptx", "target": body.target})
    return Response(_outbound(db, who, "pptx", comps_mod.to_pptx(db, res)), headers={"Content-Disposition": 'attachment; filename="comps.pptx"'},
                    media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.get("/legal/clause-library")
def legal_clause_library(who: Who):
    """What the legal review checks: each key term, the document types it applies to, and the playbook
    positions that flag a clause for a human. Pure catalogue, same rules as the extractor."""
    terms = [{"term": k, "documents": list(v["doc"])} for k, v in legal_mod.TERMS.items()]
    playbook = [{"id": r["id"], "term": r["term"], "check": r["check"], "severity": r["severity"], "text": r["text"]}
                for r in legal_mod.PLAYBOOK]
    return {"terms": terms, "playbook": playbook}


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
    if body.kind in ("alert_digest", "universe_refresh") and who.restricted:
        raise HTTPException(403, f"{body.kind} covers the whole tenant; use an unrestricted key")
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
    runs = wf_mod.run_due(db, who.tenant, visible_doc_ids(db, who), wf_mod.smtp_mailer(),
                          chat=chat_poster(pii=outbound.pii_on(db, who.tenant)))
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


SCREEN_PROFILE_KEYS = ("deal_screening_criteria", "screening_weights", "target_ev_range", "target_ebitda_range")


SCREEN_WEIGHT_KEYS = {"sector", "country", "revenue"}


def _screen_weights(raw: dict[str, float]) -> dict[str, float]:
    """Firm-set weight per criterion. Unlisted criteria weigh 1, so no weights means the plain share of tests passing."""
    bad = set(raw) - SCREEN_WEIGHT_KEYS
    if bad:
        raise HTTPException(422, f"unknown weight keys: {sorted(bad)}; use {sorted(SCREEN_WEIGHT_KEYS)}")
    if any(not 0 <= w <= 10 for w in raw.values()):
        raise HTTPException(422, "weights must be between 0 and 10")
    return {k: float(v) for k, v in raw.items()}


def _weighted_score(criteria: dict[str, str], weights: dict[str, float]) -> float | None:
    """Weighted share of the tests that pass. An unknown test counts as not passed, never as passed."""
    if not criteria:
        return None
    total = sum(weights.get(k, 1.0) for k in criteria)
    if total == 0:
        return None
    return round(sum(weights.get(k, 1.0) for k, v in criteria.items() if v == "pass") / total, 2)


class Screen(BaseModel):
    sectors: list[str] = []
    countries: list[str] = []
    min_revenue: Decimal | None = None
    max_revenue: Decimal | None = None
    weights: dict[str, float] = {}
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


@app.post("/targets/refresh")
def targets_refresh(db: Db, who: Writer, limit: int = Query(200, ge=1, le=1000)):
    """Re-pull stored SEC and Companies House targets from their sources. Each row keeps its source link."""
    return tg_mod.refresh_universe(db, who.tenant, tg_mod.live_sec_fetch, ch_mod.fetch_company, limit=limit)


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
    if mnpi_name_conflict(db, who, t.name):
        log_event(db, who.tenant, actor(who), "outreach.mnpi_blocked", {"id": t.id, "route": "send"})
        raise HTTPException(409, "outreach blocked: this target matches a deal under MNPI restriction")
    scope = deal_scope(db, who)
    name = f"research-{t.id}.docx"
    files = [(name, _outbound(db, who, "docx", research_mod.build_docx(db, who.tenant, t, scope)), DOCX_MIME)]
    if body.memo_entity:
        files.append(("memo.pptx", _outbound(db, who, "pptx", build_memo_pptx(db, who.tenant, body.memo_entity, visible_doc_ids(db, who))), PPTX_MIME))
    try:
        notify_mod.send_email(to, msg["subject"], msg["body"], files)
    except notify_mod.MailNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except OSError as e:  # SMTP host unreachable or refused: a gateway failure, not a server bug
        raise HTTPException(502, f"mail server unreachable: {e}") from e
    log_event(db, who.tenant, actor(who), "target.outreach_sent", {"id": t.id, "to": len(to)})
    return {"sent": len(to), "attached": [f[0] for f in files]}


class OutreachQueueIn(BaseModel):
    target_ids: list[int] = Field(min_length=1, max_length=200)
    sender: str = Field(min_length=1, max_length=120)
    firm: str = Field(min_length=1, max_length=120)
    thesis: str | None = Field(default=None, max_length=2000)


class OutreachReviewIn(BaseModel):
    decision: Literal["approve", "reject"]


class OutreachQueueSend(BaseModel):
    to: list[str] | None = Field(default=None, max_length=20)  # None: the target's saved contacts
    memo_entity: str | None = Field(default=None, max_length=200)


class ContactBody(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    name: str | None = Field(default=None, max_length=200)


OUTREACH_DAILY_LIMIT = int(os.environ.get("OUTREACH_DAILY_LIMIT", "50"))


def _queue_item(db: Session, who: Principal, item_id: int) -> OutreachItem:
    it = db.get(OutreachItem, item_id)
    if it is None or it.tenant_id != who.tenant:
        raise HTTPException(404, "queued draft not found")
    return it


@app.post("/targets/outreach/queue", status_code=201)
def outreach_queue(body: OutreachQueueIn, db: Db, who: Writer):
    """Put drafts in the review queue. Nothing is sent; a senior person approves each one, then sends it."""
    rows = db.query(Target).filter(Target.tenant_id == who.tenant, Target.id.in_(body.target_ids)).all()
    missing = sorted(set(body.target_ids) - {t.id for t in rows})
    if missing:
        raise HTTPException(404, f"targets not found: {missing}")
    blocked = sorted(t.id for t in rows if mnpi_name_conflict(db, who, t.name))
    if blocked:
        log_event(db, who.tenant, actor(who), "outreach.mnpi_blocked", {"ids": blocked, "route": "queue"})
        raise HTTPException(409, f"outreach blocked for targets {blocked}: they match a deal under MNPI restriction")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    items = []
    for t in rows:
        d = outreach_mod.draft(t, body.sender, body.firm, body.thesis)
        it = OutreachItem(tenant_id=who.tenant, target_id=t.id, status="pending", sender=body.sender, firm=body.firm,
                          thesis=body.thesis, subject=d["subject"], body=d["body"], created_by=actor(who), created_at=now)
        db.add(it)
        items.append(it)
    db.commit()
    log_event(db, who.tenant, actor(who), "target.outreach_queued", {"count": len(items)})
    return {"items": [{"id": it.id, "target_id": it.target_id, "status": it.status, "subject": it.subject} for it in items]}


@app.get("/targets/outreach/queue")
def outreach_queue_list(db: Db, who: Who, status: str | None = None):
    q = db.query(OutreachItem).filter_by(tenant_id=who.tenant)
    if status:
        q = q.filter_by(status=status)
    return {"items": [{"id": it.id, "target_id": it.target_id, "status": it.status, "subject": it.subject,
                       "created_by": it.created_by, "reviewed_by": it.reviewed_by} for it in q.order_by(OutreachItem.id).all()]}


@app.post("/targets/outreach/queue/{item_id}/review")
def outreach_review(item_id: int, body: OutreachReviewIn, db: Db, who: Writer):
    """Approve or reject a pending draft. Only a senior, unrestricted person's key may decide."""
    if who.role not in OUTREACH_SENDERS or who.restricted:
        raise HTTPException(403, "reviewing outreach needs a senior, unrestricted person's key")
    it = _queue_item(db, who, item_id)
    if it.status != "pending":
        raise HTTPException(409, f"draft is {it.status}, not pending")
    it.status = "approved" if body.decision == "approve" else "rejected"
    it.reviewed_by = actor(who)
    db.commit()
    return {"id": it.id, "status": it.status}


@app.post("/targets/{tid}/contacts", status_code=201)
def target_contact_add(tid: int, body: ContactBody, db: Db, who: Writer):
    """Add an address that outreach to this target may be sent to. Only a senior key's send mails it."""
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    try:
        email = notify_mod.valid_recipients([body.email])[0]
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    row = db.query(TargetContact).filter_by(tenant_id=who.tenant, target_id=t.id, email=email).one_or_none()
    if row is None:
        row = TargetContact(tenant_id=who.tenant, target_id=t.id, email=email, name=body.name)
        db.add(row)
    else:
        row.name = body.name
    db.commit()
    return {"id": row.id, "email": row.email, "name": row.name}


@app.get("/targets/{tid}/contacts")
def target_contacts(tid: int, db: Db, who: Who):
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    rows = db.query(TargetContact).filter_by(tenant_id=who.tenant, target_id=t.id).order_by(TargetContact.id).all()
    return {"items": [{"id": c.id, "email": c.email, "name": c.name} for c in rows]}


@app.post("/targets/outreach/queue/{item_id}/send")
def outreach_queue_send(item_id: int, body: OutreachQueueSend, db: Db, who: Writer):
    """Send an approved draft. The text must still match what was queued, or it goes back for review."""
    if who.role not in OUTREACH_SENDERS or who.restricted:
        raise HTTPException(403, "sending outreach needs a senior, unrestricted person's key")
    it = _queue_item(db, who, item_id)
    if it.status != "approved":
        raise HTTPException(409, f"draft is {it.status}; only an approved draft is sent")
    t = db.get(Target, it.target_id)
    if t is None:
        raise HTTPException(404, "target not found")
    addresses = body.to if body.to is not None else [c.email for c in db.query(TargetContact).filter_by(tenant_id=who.tenant, target_id=t.id).all()]
    if not addresses:
        raise HTTPException(422, "no recipients: add a contact to this target or send to addresses")
    try:
        to = notify_mod.valid_recipients(addresses)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    today = datetime.now(UTC).date().isoformat()
    sent_today = db.query(OutreachItem).filter(OutreachItem.tenant_id == who.tenant, OutreachItem.status == "sent",
                                               OutreachItem.sent_at >= today).count()
    if sent_today >= OUTREACH_DAILY_LIMIT:
        raise HTTPException(429, f"daily outreach limit of {OUTREACH_DAILY_LIMIT} reached; sends resume tomorrow")
    now_draft = outreach_mod.draft(t, it.sender, it.firm, it.thesis)
    if now_draft["subject"] != it.subject or now_draft["body"] != it.body:
        it.status = "pending"
        it.reviewed_by = None
        db.commit()
        raise HTTPException(409, "the draft changed since it was approved; it is back in the queue for review")
    if mnpi_name_conflict(db, who, t.name):
        log_event(db, who.tenant, actor(who), "outreach.mnpi_blocked", {"id": t.id, "route": "queue_send"})
        raise HTTPException(409, "outreach blocked: this target matches a deal under MNPI restriction")
    scope = deal_scope(db, who)
    files = [(f"research-{t.id}.docx", research_mod.build_docx(db, who.tenant, t, scope), DOCX_MIME)]
    if body.memo_entity:
        files.append(("memo.pptx", _outbound(db, who, "pptx", build_memo_pptx(db, who.tenant, body.memo_entity, visible_doc_ids(db, who))), PPTX_MIME))
    try:
        notify_mod.send_email(to, it.subject, it.body, files)
    except notify_mod.MailNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except OSError as e:
        raise HTTPException(502, f"mail server unreachable: {e}") from e
    it.status = "sent"
    it.sent_at = datetime.now(UTC).isoformat(timespec="seconds")
    db.commit()
    log_event(db, who.tenant, actor(who), "target.outreach_sent", {"id": t.id, "to": len(to), "queued": it.id})
    return {"sent": len(to), "attached": [f[0] for f in files]}


def _research_text(db: Session, tenant: str, template: str | None) -> dict:
    """Firm heading text and intro for the research note, from a saved template. Empty when none is named."""
    if not template:
        return {"headings": {}, "intro": ""}
    headings, intro = mt_mod.firm_text(db, tenant, template)
    return {"headings": {k: v for k, v in headings.items() if k in research_mod.RESEARCH_KEYS}, "intro": intro}


@app.get("/targets/{tid}/research.docx")
def target_research(tid: int, db: Db, who: Who, template: str | None = Query(None, max_length=64)):
    """Research note for one target: identity, revenue with filing link, sector benchmark, prior mentions, sources."""
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    log_event(db, who.tenant, actor(who), "target.research_export", {"id": tid})
    return Response(research_mod.build_docx(db, who.tenant, t, deal_scope(db, who), **_research_text(db, who.tenant, template)),
                    headers={"Content-Disposition": f'attachment; filename="research-{tid}.docx"'},
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/targets/{tid}/research.pptx")
def target_research_deck(tid: int, db: Db, who: Who, template: str | None = Query(None, max_length=64)):
    """Same research note as slides: one slide per section, built from the same records."""
    t = db.get(Target, tid)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    log_event(db, who.tenant, actor(who), "target.research_export", {"id": tid, "format": "pptx"})
    return Response(research_mod.build_pptx(db, who.tenant, t, deal_scope(db, who), **_research_text(db, who.tenant, template)),
                    headers={"Content-Disposition": f'attachment; filename="research-{tid}.pptx"'},
                    media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.get("/seen-before")
def seen_before(q: str, db: Db, who: Who):
    """Have we seen this company or deal before? Searches targets, portfolio companies and deals you can see."""
    if len(q.strip()) < 2:
        raise HTTPException(422, "query must be at least 2 characters")
    out = seen_mod.lookup(db, who.tenant, q, deal_scope(db, who))
    mnpi = set(visible_mnpi_deal_names(db, who))
    shown = sorted(h["name"] for h in out["hits"] if h["kind"] == "deal" and h["name"] in mnpi)
    if shown:  # walled-deal access audit: a cleared person saw an MNPI deal's name
        log_event(db, who.tenant, actor(who), "mnpi.view", {"route": "seen-before", "deals": shown})
    return out


@app.get("/targets/benchmark")
def targets_benchmark(db: Db, who: Who, sector: str | None = None, target_id: int | None = None):
    """Revenue median and quartiles for a sector, and where one target sits. Excludes targets with no revenue."""
    t = None
    if target_id is not None:
        t = db.get(Target, target_id)
        if t is None or t.tenant_id != who.tenant:
            raise HTTPException(404, "target not found")
    return tg_mod.benchmark(db, who.tenant, sector, t)


@app.get("/targets/{target_id}/sic-peers")
def targets_sic_peers(target_id: int, db: Db, who: Who, pages: int = Query(1, ge=1, le=3)):
    """SEC peers picked by the target's SIC code and revenue band (0.5x to 2x), each with its rule and filing link.
    Median of the peers' revenue is shown next to the target. Empty when the target has no SIC or no revenue."""
    t = db.get(Target, target_id)
    if t is None or t.tenant_id != who.tenant:
        raise HTTPException(404, "target not found")
    if not t.sic or t.revenue is None:
        return {"target_id": t.id, "sic": t.sic, "peers": [], "median": None,
                "note": "needs a SIC code and a stated revenue"}
    exclude = {t.source_ref.zfill(10)} if t.source == "sec" else set()
    rule_row = fk.newest_accepted(db, who.tenant, "peer_rules")
    rule = peers_mod.parse_rule(rule_row.value) if rule_row else peers_mod.PeerRule()
    found = peers_mod.discover_with_group(t.revenue, t.sic, exclude, pages=pages, rule=rule)
    st = comps_mod.stats([p.revenue for p in found])
    applied = {"low": str(rule.low), "high": str(rule.high), "min_year": rule.min_year,
               "min_peers": rule.min_peers, "widen": rule.widen,
               "rule_source": f"accepted peer_rules rule: {rule_row.value}" if rule_row else "default"}
    return {"target_id": t.id, "sic": t.sic, "target_revenue": str(t.revenue), "peers": len(found), "applied": applied,
            "median": None if st.median is None else str(st.median),
            "items": [{"cik": p.cik, "name": p.name, "revenue": str(p.revenue), "period": p.period,
                       "source_url": p.source_url, "rule": p.rule, "matched_on": p.matched_on} for p in found]}


class SavedScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sectors: list[str] = []
    countries: list[str] = []
    min_revenue: Decimal | None = None
    max_revenue: Decimal | None = None
    weights: dict[str, float] = {}


@app.post("/targets/screens", status_code=201)
def saved_screen_save(body: SavedScreenIn, db: Db, who: Writer):
    """Save a named screen. Saving under an existing name replaces its criteria."""
    if not (body.sectors or body.countries or body.min_revenue is not None or body.max_revenue is not None):
        raise HTTPException(422, "a saved screen needs at least one criterion")
    criteria = {"sectors": body.sectors, "countries": body.countries,
                "min_revenue": None if body.min_revenue is None else str(body.min_revenue),
                "max_revenue": None if body.max_revenue is None else str(body.max_revenue),
                "weights": _screen_weights(body.weights)}
    row = db.query(SavedScreen).filter_by(tenant_id=who.tenant, name=body.name).one_or_none()
    if row is None:
        row = SavedScreen(tenant_id=who.tenant, name=body.name, created_by=actor(who),
                          created_at=datetime.now(UTC).isoformat(timespec="seconds"))
        db.add(row)
    row.criteria = json.dumps(criteria)
    db.commit()
    return {"id": row.id, "name": row.name, "criteria": criteria}


@app.get("/targets/screens")
def saved_screen_list(db: Db, who: Who):
    rows = db.query(SavedScreen).filter_by(tenant_id=who.tenant).order_by(SavedScreen.name).all()
    return {"items": [{"id": r.id, "name": r.name, "criteria": json.loads(r.criteria)} for r in rows]}


@app.post("/targets/screens/{screen_id}/run")
def saved_screen_run(screen_id: int, db: Db, who: Who, limit: int = Query(200, ge=1, le=1000)):
    """Rerun a saved screen against the current target list, with the same screen logic as /targets/screen."""
    row = db.get(SavedScreen, screen_id)
    if row is None or row.tenant_id != who.tenant:
        raise HTTPException(404, "screen not found")
    c = json.loads(row.criteria)
    body = Screen(sectors=c["sectors"], countries=c["countries"],
                  min_revenue=None if c["min_revenue"] is None else Decimal(c["min_revenue"]),
                  max_revenue=None if c["max_revenue"] is None else Decimal(c["max_revenue"]),
                  weights=c.get("weights", {}), limit=limit)
    return {"screen": row.name, **targets_screen(body, db, who)}


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
    weight_rule = fk.newest_accepted(db, who.tenant, "screening_weights")
    weights = _screen_weights(body.weights or (al.screening_weights(weight_rule.value) if weight_rule else {}))
    out = []
    for t in db.query(Target).filter_by(tenant_id=who.tenant).order_by(Target.id).all():
        e = tg_mod.evaluate(t, c)
        if e["verdict"] != "fail":
            d = tg_mod.to_dict(t)
            sources = [{"label": lbl, "url": u} for lbl, u in
                       (("company record", d["source_url"]), ("revenue", d["revenue_url"])) if u]
            # score: share of the criteria that pass; an unknown criterion counts as not passed, never as passed
            score = _weighted_score(e["criteria"], weights)
            out.append({**d, **e, "sources": sources, "score": score})
    out.sort(key=lambda r: (r["verdict"] != "match", -(r["score"] or 0)))
    profile = [fk.row_dict(r) for r in (fk.newest_accepted(db, who.tenant, k)
                                        for k in SCREEN_PROFILE_KEYS) if r is not None]
    return {"matches": sum(r["verdict"] == "match" for r in out), "review": sum(r["verdict"] == "review" for r in out),
            "criteria_profile": profile, "criteria_source": source,
            "applied": {"sectors": c.sectors, "countries": c.countries, "weights": weights,
                        "weights_source": None if body.weights or weight_rule is None else {"key": weight_rule.key, "value": weight_rule.value, "document_id": weight_rule.document_id, "page": weight_rule.page, "quote": weight_rule.quote},
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
    blocked = sorted(t.id for t in rows if mnpi_name_conflict(db, who, t.name))
    if blocked:
        log_event(db, who.tenant, actor(who), "outreach.mnpi_blocked", {"ids": blocked, "route": "draft"})
        raise HTTPException(409, f"drafts blocked for targets {blocked}: they match a deal under MNPI restriction")
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
    return Response(_outbound(db, who, "docx", build_report_docx(db, who.tenant, visible_doc_ids(db, who))), headers={
        "Content-Disposition": 'attachment; filename="portfolio-report.docx"'},
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/portfolio/companies/{company_id}/change")
def change(company_id: int, metric: str, new: str, old: str, db: Db, tenant: Tenant):
    v = qoq_change(db, tenant, company_id, metric, new, old)
    return {"metric": metric, "new": new, "old": old,
            "pct_change": None if v is None else str(v.quantize(Decimal("0.01")))}


@app.post("/audit/archive")
def audit_archive_run(db: Db, who: Who):
    """Archive audit rows older than AUDIT_RETENTION_YEARS to AUDIT_ARCHIVE_DIR. Admin only; whole-tenant keys.
    Archives are copies with chain anchors. Nothing is deleted from the live trail."""
    if who.restricted:
        raise HTTPException(403, "archiving covers the whole tenant; use an unrestricted key")
    _require(who, "purge", "archive the audit trail")
    out_dir = os.environ.get("AUDIT_ARCHIVE_DIR")
    if not out_dir:
        raise HTTPException(409, "set AUDIT_ARCHIVE_DIR on the server before archiving")
    try:
        result = audit_archive.archive(db, who.tenant, out_dir)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "audit.archive", {"archived": result["archived"]})
    db.commit()
    return result


@app.get("/compliance/access-report")
def access_report(deal: str, db: Db, who: Who, limit: int = Query(500, ge=1, le=5000)):
    """Who did what to one deal, from the audit chain: every logged event that names the deal, with a count per
    person. Only actions the trail records appear. Reading a document is not logged, so it is not here."""
    if who.restricted:
        raise HTTPException(403, "the access report covers the whole tenant; use an unrestricted key")
    _require(who, "govern", "read the access report", deal=deal)
    rows = (db.query(AuditEvent).filter_by(tenant_id=who.tenant).order_by(AuditEvent.id.desc())
            .limit(limit * 10).all())
    events = []
    for r in rows:
        payload = json.loads(r.payload)
        names = {payload.get("name"), payload.get("deal"), *(payload.get("deals") or [])}
        if deal in names:
            events.append({"ts": r.ts, "actor": r.actor, "action": r.action, "payload": payload})
        if len(events) >= limit:
            break
    per_actor: dict[str, int] = {}
    for e in events:
        per_actor[e["actor"]] = per_actor.get(e["actor"], 0) + 1
    return {"deal": deal, "events": events, "by_actor": per_actor,
            "note": "Logged actions only. Document reads are not in the audit trail."}


@app.get("/audit")
def audit_list(db: Db, who: Who, action: str | None = None, limit: int = Query(100, ge=1, le=500)):
    """The tenant's audit chain, newest first. Whole-tenant keys only: the trail names every deal."""
    if who.restricted:
        raise HTTPException(403, "the audit trail covers the whole tenant; use an unrestricted key")
    q = db.query(AuditEvent).filter_by(tenant_id=who.tenant)
    if action:
        q = q.filter_by(action=action)
    rows = q.order_by(AuditEvent.id.desc()).limit(limit).all()
    return {"items": [{"id": r.id, "ts": r.ts, "actor": r.actor, "action": r.action,
                       "payload": json.loads(r.payload)} for r in rows]}


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


def llm_dependency(db: Db, who: Who) -> LLM:
    try:
        return get_llm(db, who.tenant)
    except NoLLMConfigured as e:
        raise HTTPException(503, str(e)) from e


@app.exception_handler(LLMCapExceeded)
def llm_cap_handler(request, exc: LLMCapExceeded):
    return JSONResponse(status_code=429, content={"detail": str(exc)})


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


class RowExtractIn(BaseModel):
    schema_name: str
    period: str
    entity: str | None = None  # the company the table is about; bridge lines are stored under it


@app.post("/documents/{doc_id}/extract-rows")
def extract_row_table(doc_id: str, body: RowExtractIn, db: Db, who: Writer,
                      llm: Annotated[LLM, Depends(llm_dependency)]):
    """Row tables (cap table, contract terms). Each row is cited by page and quote and stays `auto` until reviewed."""
    doc = _own_doc(db, who, doc_id)
    if body.schema_name not in ROW_SCHEMAS:
        raise HTTPException(422, f"schema must be one of {sorted(ROW_SCHEMAS)}")
    if body.schema_name == "ebitda_bridge" and not body.entity:
        raise HTTPException(422, "ebitda_bridge needs the company name in entity")
    results, detail, checks = extract_rows(db, who.tenant, llm, doc, body.schema_name, body.period, body.entity)
    log_event(db, who.tenant, actor(who), "extract_rows",
              {"document_id": doc.id, "schema": body.schema_name,
               "accepted": sum(r.status == "accepted" for r in results)})
    return {"schema": body.schema_name, "detail": detail,
            "rows": [{"status": r.status, "page": r.page, "reason": r.reason, "fact_ids": r.fact_ids}
                     for r in results],
            "bridge_checks": checks}


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
    scope = visible_doc_ids(db, who)
    k = answer_cache.key(body.question, body.doc_id, answer_cache.visible_docs(db, tenant, scope), llm_id(llm))
    a = answer_cache.get(db, tenant, k)
    cached = a is not None
    if a is None:
        a = answer_question(db, tenant, llm, body.question, body.doc_id, scope=scope)
        answer_cache.put(db, tenant, k, a)
    log_event(db, tenant, actor(who), "ask", {"question": body.question, "status": a.status,
                                         "claims": len(a.claims), "rejected": len(a.rejected), "cached": cached})
    cite = lambda c: {"text": c.text, "document_id": c.doc_id, "page": c.page, "quote": c.quote,
                      "paragraphs": c.paragraphs}
    return {"status": a.status, "detail": a.detail, "claims": [cite(c) for c in a.claims],
            "rejected": [{**cite(c), "reason": c.reason} for c in a.rejected],
            "prompt_version": a.prompt_version, "model": a.model, "cached": cached}


@app.post("/chat/{kind}/inbound")
async def chat_inbound(kind: str, request: Request, db: Db):
    """A Slack slash command or Teams outgoing webhook asks a question. The request must carry the chat app's
    signature; the question runs as that app's configured key, so its scope and MNPI walls apply."""
    if kind not in ("slack", "teams"):
        raise HTTPException(404, "unknown chat app")
    body = await request.body()
    secret = os.environ.get("SLACK_SIGNING_SECRET" if kind == "slack" else "TEAMS_SECURITY_TOKEN")
    if not secret:
        raise HTTPException(503, f"{kind} inbound is not configured")
    if kind == "slack":
        ok = verify_slack(secret, request.headers.get("X-Slack-Request-Timestamp", ""),
                          request.headers.get("X-Slack-Signature", ""), body, int(time.time()))
        question = slack_question(body)
    else:
        ok = verify_teams(secret, request.headers.get("Authorization"), body)
        question = teams_question(body)
    if not ok:
        raise HTTPException(401, "bad signature")
    reply = slack_reply if kind == "slack" else teams_reply
    if not question:
        return reply(HELP)
    who = principal_for_identity(db, chat_identity(kind, body))
    if who is None:
        return reply(NOT_LINKED)
    bind_tenant(db, who.tenant)
    a = answer_question(db, who.tenant, llm_dependency(db, who), question, scope=visible_doc_ids(db, who))
    filenames = {d.id: d.filename for d in db.query(Document).filter(
        Document.tenant_id == who.tenant, Document.id.in_([c.doc_id for c in a.claims] or [""]))}
    log_event(db, who.tenant, who.identity or f"chat:{kind}", "chat.ask", {"question": question, "status": a.status,
                                                                         "claims": len(a.claims), "rejected": len(a.rejected)})
    db.commit()
    return reply(format_answer(a, filenames))


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


def optional_llm_dependency(db: Db, who: Who):
    try:
        return get_llm(db, who.tenant)
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
    rows = {r.connector: r for r in db.query(Connection).filter_by(tenant_id=who.tenant)}
    out = status(set(rows))
    for c in out:
        if c["name"] in rows:
            c.update(connection_health(rows[c["name"]]))
    return out


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


@app.post("/webhooks/docusign")
async def docusign_connect(request: Request, tenant: str, db: Db):
    """DocuSign Connect: an envelope status change for one tenant (?tenant=...). The body is checked against
    X-DocuSign-Signature-1 (base64 HMAC-SHA256 of the raw body, keyed by DOCUSIGN_CONNECT_HMAC_KEY) before anything
    is read. Without the key configured the route is off (503); a bad signature is a 401 and changes nothing."""
    key = os.environ.get("DOCUSIGN_CONNECT_HMAC_KEY", "")
    if not key:
        raise HTTPException(503, "DocuSign Connect is not configured")
    raw = await request.body()
    # One header per HMAC key defined on the Connect config (X-DocuSign-Signature-1 .. -100); any one matching is
    # enough. Source: https://www.docusign.com/blog/event-notifications-using-json-sim-and-hmac (header names, HMAC-SHA256
    # over the body). The base64 encoding is not confirmed by that page; see docs/MOCKS.md.
    expected = base64.b64encode(hmac.new(key.encode(), raw, hashlib.sha256).digest()).decode()
    sent = [v for n, v in ((n, request.headers.get(f"X-DocuSign-Signature-{n}")) for n in range(1, 101)) if v]
    if not any(hmac.compare_digest(v, expected) for v in sent):
        raise HTTPException(401, "bad signature")
    if db.get(TenantRow, tenant) is None:
        raise HTTPException(404, "tenant not found")
    bind_tenant(db, tenant)  # no bearer token on this route: the signature is the only credential
    try:
        parsed = parse_connect(json.loads(raw))
    except ValueError as e:
        raise HTTPException(422, "body is not JSON") from e
    if parsed is None:
        raise HTTPException(422, "envelopeId, status and emailSubject are required")
    envelope_id, status, subject = parsed
    deal = deal_for_subject(db, tenant, subject)
    changed = None
    if deal is not None:
        before = deal.stage
        deal.stage = advance(deal.stage, status)
        if deal.stage != before:
            deal.updated_at = _now_iso()
            changed = {"deal": deal.name, "stage_before": before, "stage_after": deal.stage}
            db.commit()
    log_event(db, tenant, "docusign-connect", "docusign.webhook",
              {"envelope": envelope_id, "status": status, "deal": deal.name if deal else None,
               "changed": changed is not None})
    return {"envelope": envelope_id, "changed": changed}


@app.post("/connectors/docusign/stage-sync")
def docusign_stage_sync(body: SyncBody, db: Db, who: Writer):
    """Move one deal's stage on its completed DocuSign envelopes (subject = the deal name, then a space or the end).
    Only a deal in this key's scope can be moved, and only forward (app/envelope_stage.py)."""
    deal = (body.deal or "").strip()
    if not deal:
        raise HTTPException(422, "deal is required")
    _require(who, "write", "move a deal stage from DocuSign", deal=deal)
    if who.restricted and deal not in who.deals:
        raise HTTPException(403, "deal is required and must be within this key's scope")
    d = db.query(Deal).filter_by(tenant_id=who.tenant, name=deal).first()
    if d is None or deal_hidden(d, who):
        raise HTTPException(404, "deal not found")
    try:
        envelopes = DocuSign(body.token, CONNECTOR_HTTP, **body.options).envelopes()
    except (ConnectorError, ValueError, OSError) as e:
        raise HTTPException(502, f"docusign failed: {e}") from e
    before, applied = d.stage, []
    for e in sorted(envelopes, key=lambda x: x["completedDateTime"]):
        subject = e["emailSubject"]
        if subject != deal and not subject.startswith(deal + " "):
            continue
        new = advance(d.stage, e["status"])
        if new != d.stage:
            d.stage = new
            applied.append(e["envelopeId"])
    if applied:
        d.updated_at = _now_iso()
        db.commit()
    log_event(db, who.tenant, actor(who), "docusign.stage_sync",
              {"deal": deal, "stage_before": before, "stage_after": d.stage, "envelopes": applied})
    return {"deal": deal, "stage_before": before, "stage_after": d.stage, "envelopes": applied}


@app.post("/connectors/{name}/stage-sync")
def stage_sync_connector(name: str, body: SyncBody, db: Db, who: Writer):
    """Two-way deal-stage sync with a CRM. Unrestricted keys only: it reads and writes stages across deals."""
    _unrestricted(who)
    cls = IMPLEMENTED.get(name)
    if cls is None:
        raise HTTPException(404, "connector not implemented")
    try:
        conn = cls(body.token, CONNECTOR_HTTP, **body.options)
        out = run_stage_sync(db, who.tenant, conn, max(1, min(body.limit, 500)))
    except (ConnectorError, ValueError, OSError) as e:
        raise HTTPException(502, f"stage sync failed: {e}") from e
    log_event(db, who.tenant, actor(who), "connector.stage_sync", {"connector": name, **out})
    return out


class PeopleIn(BaseModel):
    ch_number: str | None = None  # Companies House company number
    sec_url: str | None = None  # https sec.gov filing URL
    sec_form: str = "10-K"  # label shown on each person's citation: 10-K or DEF 14A


@app.post("/enrich/people")
def enrich_people(body: PeopleIn, who: Who):
    """Named people for a company from public sources (LinkedIn alternative). Every person is cited."""
    if body.sec_form not in ("10-K", "DEF 14A"):
        raise HTTPException(422, "sec_form must be 10-K or DEF 14A")
    out: list[dict] = []
    try:
        if body.ch_number:
            out += pe_mod.companies_house_people(body.ch_number)
        if body.sec_url:
            out += pe_mod.sec_people(body.sec_url, body.sec_form)
    except (ValueError, RuntimeError, OSError, chfeed.CompanyNotFound) as e:
        raise HTTPException(502, f"enrichment failed: {e}") from e
    return {"people": out}


@app.post("/portfolio/companies/{company_id}/kpi-pack")
async def upload_kpi_pack(company_id: int, file: Annotated[UploadFile, File()], db: Db, who: Writer):
    """Monthly KPI workbook for a portfolio company. Each row becomes a cited observation."""
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    try:
        out = kpi_pack_ingest(db, who.tenant, company_id, data, file.filename or "kpi-pack.xlsx")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    log_event(db, who.tenant, actor(who), "portfolio.kpi_pack",
              {"company_id": company_id, "observations": len(out.observations), "skipped": len(out.skipped)})
    return {"observations": out.observations, "skipped": out.skipped, "unchanged": out.unchanged}


@app.post("/targets/{tid}/funding-import")
async def target_funding_import(tid: int, file: Annotated[UploadFile, File()], db: Db, who: Writer):
    """Funding history for a target from a Crunchbase legacy funding_rounds CSV. Each round cites its row."""
    target = db.query(Target).filter_by(tenant_id=who.tenant, id=tid).first()
    if target is None:
        raise HTTPException(404, "target not found")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD} bytes")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "funding_rounds.csv"
        path.write_bytes(data)
        try:
            rows = read_funding_rounds_numbered(path)
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            raise HTTPException(422, f"not a Crunchbase funding_rounds export: {e}") from e
    source = file.filename or "funding_rounds.csv"
    return {"target": target.name, "rows_read": len(rows),
            "rounds": funding_for_target(rows, target.name, source)}


@app.get("/documents/{doc_id}/source")
def document_source(doc_id: str, db: Db, who: Who):
    """Link back to the original in the source system, for audit and citation."""
    _own_doc(db, who, doc_id)
    s = db.query(DocumentSource).filter_by(document_id=doc_id).order_by(DocumentSource.id.desc()).first()
    if s is None:
        raise HTTPException(404, "document was uploaded manually; no connector source")
    return {"connector": s.connector, "url": s.url, "version": s.version, "sync_run_id": s.sync_run_id}


@app.get("/sync-runs")
def list_sync_runs(who: Who, db: Db, limit: int = 25):
    """Recent connector syncs, newest first. Restricted keys see only runs on deals in their scope."""
    q = db.query(SyncRun).filter_by(tenant_id=who.tenant)
    if who.restricted:
        q = q.filter(SyncRun.deal.in_(who.deals))
    rows = q.order_by(SyncRun.id.desc()).limit(max(1, min(limit, 200))).all()
    return [_run_dict(r) for r in rows]


@app.get("/sync-runs/{run_id}")
def get_sync_run(run_id: int, who: Who, db: Db):
    """One sync and every document it brought in, each with its source link."""
    run = db.query(SyncRun).filter_by(tenant_id=who.tenant, id=run_id).first()
    if run is None or (who.restricted and run.deal not in who.deals):
        raise HTTPException(404, "sync run not found")
    items = (db.query(DocumentSource, Document.filename)
             .join(Document, Document.id == DocumentSource.document_id)
             .filter(DocumentSource.tenant_id == who.tenant, DocumentSource.sync_run_id == run_id)
             .order_by(DocumentSource.id).all())
    return {**_run_dict(run), "documents": [
        {"document_id": s.document_id, "filename": fn, "external_id": s.external_id, "version": s.version,
         "source_url": s.url} for s, fn in items]}


def _run_dict(r: SyncRun) -> dict:
    return {"id": r.id, "connector": r.connector, "connection_id": r.connection_id, "deal": r.deal,
            "started_at": r.started_at, "finished_at": r.finished_at, "status": r.status,
            "ingested": r.ingested, "unchanged": r.unchanged, "skipped": r.skipped, "error": r.error}


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


class DigestPrefBody(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    min_severity: Literal["critical", "warning", "info"] = "info"


def _signed_in_subject(who: Principal) -> str:
    # OIDC tokens carry the account's subject as key_id ("oidc:<sub>"); API keys have no person behind them.
    if not who.key_id.startswith("oidc:"):
        raise HTTPException(403, "digest preferences belong to a signed-in person; sign in with SSO")
    return who.key_id[len("oidc:"):]


@app.put("/me/digest")
def put_my_digest(body: DigestPrefBody, db: Db, who: Who):
    """Set this person's alert digest: where it goes and the least severe alert it includes."""
    subject = _signed_in_subject(who)
    row = db.query(DigestPref).filter_by(tenant_id=who.tenant, subject=subject).one_or_none()
    if row is None:
        row = DigestPref(tenant_id=who.tenant, subject=subject, last_alert_id=0)
        db.add(row)
    row.email, row.min_severity = body.email, body.min_severity
    db.commit()
    return {"email": row.email, "min_severity": row.min_severity}


@app.post("/me/digest/send")
def send_my_digest(db: Db, who: Who):
    """Email this person the new alerts at their severity or above, within their deal scope. Only their own watermark moves."""
    subject = _signed_in_subject(who)
    row = db.query(DigestPref).filter_by(tenant_id=who.tenant, subject=subject).one_or_none()
    if row is None:
        raise HTTPException(404, "set your digest first with PUT /me/digest")
    try:
        # A deal-scoped sign-in gets only the deal alerts for its own deals; a whole-tenant sign-in gets all.
        n = notify.send_personal_digest(db, who.tenant, row, None if who.deals is None else set(who.deals),
                                        hidden=hidden_deal_names(db, who))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except notify.MailNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    return {"sent": n}


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
    try:
        tok = oauth.refresh(oauth.config_for(row.connector), vault.unseal(row.token_sealed), CONNECTOR_HTTP)
    except OAuthError as e:
        raise ConnectorError(f"token refresh failed, reconnect the account: {e}") from e
    if tok.get("refresh_token"):
        row.token_sealed = vault.seal(tok["refresh_token"])
    return tok["access_token"]


def _run_connection(db: Session, who: Principal, row: Connection) -> dict:
    cls = IMPLEMENTED[row.connector]
    try:
        opts = json.loads(row.options)
        token = _oauth_access_token(row) if opts.pop("auth", None) == "oauth" else vault.unseal(row.token_sealed)
        conn = cls(token, CONNECTOR_HTTP, **opts)
        out = connector_sync(db, who, conn, row.deal, connection_id=row.id)
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
