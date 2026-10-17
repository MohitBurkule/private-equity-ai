"""Core tables. A Fact cannot exist without a FactSource (citation is mandatory)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.citations import locator_label
from app.db import Base


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    # When on, personal identifiers are stripped from anything that leaves the system: digests, chat posts,
    # and workbook and LP exports. Figures are never changed.
    pii_redaction: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class ApiKey(Base):
    __tablename__ = "api_key"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, server_default="false")
    role: Mapped[str] = mapped_column(String(16), default="analyst", server_default="analyst")
    deals: Mapped[str | None] = mapped_column(Text, default=None)  # comma list; None = unrestricted
    deal_roles: Mapped[str | None] = mapped_column(Text, default=None)  # "deal:role,deal:role" overrides
    identity: Mapped[str | None] = mapped_column(String(256), default=None)  # the person's external id, e.g. email
    groups: Mapped[str | None] = mapped_column(Text, default=None)  # comma list of external group ids


class Document(Base):
    __tablename__ = "document"
    # id = sha256(tenant_id:content_sha256): same file in two tenants never collides or leaks existence
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(512))
    n_pages: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="pdf")
    deal: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    # When the document was stored. NULL means unknown, and retention treats unknown age as too young to purge.
    created_at: Mapped[str | None] = mapped_column(String(40), default=lambda: datetime.now(UTC).isoformat())
    pages: Mapped[list[PageRow]] = relationship(back_populates="document", cascade="all")


class DocumentFile(Base):
    """Original file bytes (PDF or filing HTML), kept so a citation can show the page as filed."""
    __tablename__ = "document_file"
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    media_type: Mapped[str] = mapped_column(String(64), default="application/pdf")


class PageRow(Base):
    __tablename__ = "page"
    __table_args__ = (UniqueConstraint("document_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1-based
    text: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(256), default=None)  # sheet name
    method: Mapped[str] = mapped_column(String(16), default="text", server_default="text")  # text | ocr
    ocr_confidence: Mapped[float | None] = mapped_column(default=None)
    spans: Mapped[str | None] = mapped_column(Text, default=None)  # JSON [[start, end, paragraph]], DOCX only
    document: Mapped[Document] = relationship(back_populates="pages")


class Fact(Base):
    __tablename__ = "fact"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(256))
    metric: Mapped[str] = mapped_column(String(256))
    period: Mapped[str] = mapped_column(String(64))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    unit: Mapped[str] = mapped_column(String(32))
    basis: Mapped[str] = mapped_column(String(16), default="GAAP")
    status: Mapped[str] = mapped_column(String(16), default="auto")
    reviewed_by: Mapped[str | None] = mapped_column(String(64), default=None)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), default=None)
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    # date the figure was true as of, when the source states one (e.g. a market close); None when it does not
    as_of: Mapped[str | None] = mapped_column(String(32), default=None)
    sources: Mapped[list[FactSource]] = relationship(back_populates="fact", cascade="all")


class FactSource(Base):
    __tablename__ = "fact_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("fact.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False)
    # PDF citations use page. HTML filings have no pages: page is 0 and the location is section/anchor/offset.
    # Workbooks: page is the stored text chunk, and the location is heading (sheet), anchor (cell), section (row).
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default="pdf", server_default="pdf")  # pdf | html | xlsx
    section: Mapped[str | None] = mapped_column(String(32), default=None)
    heading: Mapped[str | None] = mapped_column(String(256), default=None)
    anchor: Mapped[str | None] = mapped_column(String(128), default=None)
    offset: Mapped[int | None] = mapped_column(Integer, default=None)
    fact: Mapped[Fact] = relationship(back_populates="sources")

    @property
    def locator(self) -> str:
        return locator_label(self.page, self.section, self.heading, kind=self.kind, anchor=self.anchor)


class HtmlUnit(Base):
    """A text block of an HTML filing, in document order. Citations to HTML point at these."""
    __tablename__ = "html_unit"
    __table_args__ = (UniqueConstraint("document_id", "idx"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(32), default=None)
    heading: Mapped[str | None] = mapped_column(String(256), default=None)
    anchor: Mapped[str | None] = mapped_column(String(128), default=None)
    offset: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class IngestJob(Base):
    """Background upload. Bytes are spooled to disk so a restart can pick the job up again."""
    __tablename__ = "ingest_job"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    deal: Mapped[str | None] = mapped_column(String(128), default=None)
    role: Mapped[str] = mapped_column(String(16), default="analyst")
    scope: Mapped[str | None] = mapped_column(Text, default=None)  # comma deals of the submitting key
    key_id: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    files_total: Mapped[int] = mapped_column(Integer, default=0)  # members of the archive being read
    files_done: Mapped[int] = mapped_column(Integer, default=0)
    current_file: Mapped[str | None] = mapped_column(String(512), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    result: Mapped[str | None] = mapped_column(Text, default=None)  # JSON
    spool_path: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[str] = mapped_column(String(40), default="")


class DDRequest(Base):
    """One line of a due-diligence request list. Linking a document marks it received."""
    __tablename__ = "dd_request"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | received | waived
    document_id: Mapped[str | None] = mapped_column(ForeignKey("document.id"), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[str] = mapped_column(String(40), default="")


class DealNote(Base):
    """A shared note on a deal, visible to everyone who can see the deal (the deal's own visibility rules apply)."""
    __tablename__ = "deal_note"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(128), index=True)
    author: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default="")
    # A note made from a calendar meeting: the event it came from, and the link that cites it
    calendar_event_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, default=None)
    edited_at: Mapped[str] = mapped_column(String(40), default="")  # set on each edit; empty when never edited


class DDQuestion(Base):
    """A question put to management or the seller. Answers stay open until someone records one; a document can
    be linked as the answer's source, and only a document the asker can see may be linked."""
    __tablename__ = "dd_question"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(128), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("dd_request.id"), default=None)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | answered
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("document.id"), default=None)
    asked_at: Mapped[str] = mapped_column(String(40), default="")
    answered_at: Mapped[str | None] = mapped_column(String(40), default=None)
    # The citation for an answer: the page or block the answer came from, and the quote that is printed there.
    page: Mapped[int | None] = mapped_column(Integer, default=None)
    quote: Mapped[str | None] = mapped_column(Text, default=None)


class ICDecision(Base):
    """Append-only record of an investment decision: outcome, rationale, and any dissent on the record. Rows are
    never edited or deleted, so a later change of mind is a new row, not a rewrite of the old one."""
    __tablename__ = "ic_decision"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(128), index=True)
    outcome: Mapped[str] = mapped_column(String(32))  # proceed | pass | hold | more_diligence
    rationale: Mapped[str] = mapped_column(Text)
    dissent: Mapped[str | None] = mapped_column(Text, default=None)
    dissenter: Mapped[str | None] = mapped_column(String(128), default=None)
    recorded_at: Mapped[str] = mapped_column(String(40), default="")


# Ordered deal pipeline. Order matters for reporting; "closed" and "passed" end a deal and gate retention.
STAGES = ["sourcing", "screening", "nda", "cim", "ioi", "loi", "dd", "ic", "signed", "closed", "passed"]


class Deal(Base):
    """A deal workspace: name, stage and note. Documents and DD items refer to it by name."""
    __tablename__ = "deal"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(16), default="sourcing")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    # Set by compliance: a held deal cannot be deleted until the hold is lifted.
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Material non-public information: visible only to keys scoped to this deal by name.
    mnpi: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Ethical wall: JSON list of lowercased grants (identities, or "group:<id>") that may not see this deal.
    # Null means no wall. Set by admins only (see acl.parse_wall).
    wall: Mapped[str | None] = mapped_column(Text, default=None)
    # Same SIC code as portfolio companies, so precedents compare like with like.
    sic: Mapped[str | None] = mapped_column(String(8), default=None)
    # Sponsor (PE owner) of the target; "have we seen this sponsor before" matches on it.
    sponsor: Mapped[str | None] = mapped_column(String(128), default=None)
    # Other names the target trades or is filed under, comma-separated; the firm's own list, not a registry feed.
    aliases: Mapped[str | None] = mapped_column(Text, default=None)
    # Registry identifiers, so a filing or a CRM record matches the deal exactly rather than by name.
    cik: Mapped[str | None] = mapped_column(String(10), default=None, index=True)
    lei: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    # Key id that flagged the deal MNPI; that key keeps access so its creator is not locked out.
    created_by: Mapped[str | None] = mapped_column(String(64), default=None)
    updated_at: Mapped[str] = mapped_column(String(40), default="")


class DealChecklistItem(Base):
    """A deal-level checklist line (e.g. "IC memo drafted"), separate from the DD request list."""
    __tablename__ = "deal_checklist_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_at: Mapped[str] = mapped_column(String(40), default="")


class ValuationRound(Base):
    """One round or valuation mark from a user-supplied export, tied to the file and CSV line it came from."""
    __tablename__ = "valuation_round"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    company: Mapped[str] = mapped_column(String(256))
    round_date: Mapped[str] = mapped_column(String(10))
    round_type: Mapped[str] = mapped_column(String(64))
    post_money: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    currency: Mapped[str] = mapped_column(String(3))
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"))
    line: Mapped[int] = mapped_column(Integer)


class Holding(Base):
    """One row of a user-supplied secondary-market holdings export, tied to the file it came from."""
    __tablename__ = "holding"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(64))
    company: Mapped[str] = mapped_column(String(256))
    shares: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    currency: Mapped[str] = mapped_column(String(3))
    acquired: Mapped[str | None] = mapped_column(String(10), default=None)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"))
    line: Mapped[int] = mapped_column(Integer)


class EvalRun(Base):
    """One run of an evaluation suite: free-form metrics as JSON, so the dashboard shows what the suite reports."""
    __tablename__ = "eval_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    suite: Mapped[str] = mapped_column(String(64), index=True)
    metrics: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    ran_at: Mapped[str] = mapped_column(String(40))
    recorded_by: Mapped[str] = mapped_column(String(64))


class FirmKnowledge(Base):
    """One cited rule or preference of the firm (see firm_knowledge.py). Quote is mandatory."""
    __tablename__ = "firm_knowledge"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"))
    page: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    prompt_version: Mapped[str] = mapped_column(String(32), default="", server_default="")
    model: Mapped[str] = mapped_column(String(128), default="", server_default="")  # provider:model that wrote it


class AgentRun(Base):
    """One workflow or agent run: its steps and result, kept for audit and replay."""
    __tablename__ = "agent_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # workflow | agent
    name: Mapped[str] = mapped_column(String(64))
    goal: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16))  # done | failed
    steps: Mapped[str] = mapped_column(Text)  # JSON
    result: Mapped[str | None] = mapped_column(Text, default=None)  # JSON
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[str] = mapped_column(String(40), default="")


class DocumentSource(Base):
    """Where a connector-synced document came from: the link every citation can open."""
    __tablename__ = "document_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    connector: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(512))
    version: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_run.id"), default=None, index=True)
    # JSON list of lowercase external ids the source grants access to. NULL = the source sets no access list.
    acl: Mapped[str | None] = mapped_column(Text, default=None)


class SyncRun(Base):
    """One connector sync: which connection (or manual call) pulled what, when, and how it ended."""
    __tablename__ = "sync_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    connector: Mapped[str] = mapped_column(String(32))
    connection_id: Mapped[int | None] = mapped_column(default=None)  # None for a manual sync call
    deal: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), default=None)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running, ok, error
    ingested: Mapped[int] = mapped_column(default=0)
    unchanged: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class WorkflowSchedule(Base):
    """A recurring job (portfolio report, comps) run on a cadence; result is mailed or left in the outbox."""
    __tablename__ = "workflow_schedule"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))  # portfolio_report | comps
    params: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    every_days: Mapped[int] = mapped_column(Integer)
    recipients: Mapped[str] = mapped_column(Text, default="")  # comma separated
    next_run: Mapped[str] = mapped_column(String(40))  # ISO UTC
    last_run: Mapped[str | None] = mapped_column(String(40), default=None)
    last_status: Mapped[str | None] = mapped_column(String(16), default=None)  # ok | failed
    last_result: Mapped[str | None] = mapped_column(Text, default=None)  # JSON or error text
    active: Mapped[int] = mapped_column(Integer, default=1)


class Target(Base):
    """An acquisition / add-on candidate with its provenance. Revenue is only set when a source states it."""
    __tablename__ = "target"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "source_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(String(32))  # sec | companies_house | manual
    source_ref: Mapped[str] = mapped_column(String(64))  # CIK, company number, or your own key
    source_url: Mapped[str | None] = mapped_column(Text, default=None)
    sector: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    sic: Mapped[str | None] = mapped_column(String(8), default=None)
    country: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    region: Mapped[str | None] = mapped_column(String(64), default=None)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), default=None)
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), default=None)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), default=None)
    currency: Mapped[str | None] = mapped_column(String(8), default=None)
    revenue_period: Mapped[str | None] = mapped_column(String(32), default=None)
    revenue_url: Mapped[str | None] = mapped_column(Text, default=None)  # where the revenue figure is filed
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | screened | contacted | passed
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    website: Mapped[str | None] = mapped_column(Text, default=None)  # https homepage the fields below came from
    web_title: Mapped[str | None] = mapped_column(Text, default=None)
    web_description: Mapped[str | None] = mapped_column(Text, default=None)
    web_site_name: Mapped[str | None] = mapped_column(Text, default=None)
    web_checked_at: Mapped[str | None] = mapped_column(String(40), default=None)


class MemoTemplate(Base):
    """A firm's own memo layout: which section keys it carries, in order. Built-in templates stay available."""
    __tablename__ = "memo_template"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64))
    sections: Mapped[str] = mapped_column(Text)  # JSON list of section keys
    headings: Mapped[str] = mapped_column(Text, default="{}")  # JSON: section key -> firm heading text
    intro: Mapped[str] = mapped_column(Text, default="")  # firm line printed under the memo title
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")


class MemoVersion(Base):
    """A saved IC memo draft. Stored as the text the reviewer saw, so a later reader sees the same figures and sources."""
    __tablename__ = "memo_version"
    __table_args__ = (UniqueConstraint("tenant_id", "entity", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(200))
    number: Mapped[int] = mapped_column()
    markdown: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")


class MemoComment(Base):
    __tablename__ = "memo_comment"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("memo_version.id"), index=True)
    author: Mapped[str] = mapped_column(String(64), default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default="")


class SavedSearch(Base):
    """A search the team reruns across the documents it can see. Runs under the rerunning person's own access."""
    __tablename__ = "saved_search"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")


class SavedScreen(Base):
    """A named strategy screen the team reruns: its criteria as entered, so a rerun applies the same tests."""
    __tablename__ = "saved_screen"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    criteria: Mapped[str] = mapped_column(Text)  # JSON: sectors, countries, min_revenue, max_revenue
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")


class TargetNote(Base):
    """A shared note on a target. Visible to everyone who can see the target, except when the target is the
    same company as an MNPI deal the key may not see (then the target is hidden, so its notes are too)."""
    __tablename__ = "target_note"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    author: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default="")
    edited_at: Mapped[str] = mapped_column(String(40), default="")


class DealDeletion(Base):
    """A pending request to delete a deal for good. The delete itself is the confirm step and needs an admin;
    a legal hold or linked documents stop it at either step."""
    __tablename__ = "deal_deletion"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(200), index=True)
    requested_by: Mapped[str] = mapped_column(String(64), default="")
    requested_at: Mapped[str] = mapped_column(String(40), default="")


class LlmUsage(Base):
    """Characters sent to and received from the language model for one tenant on one UTC day."""
    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("tenant_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(10))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)


class AnswerCache(Base):
    """A previous /ask answer, keyed on question, visible documents with their hashes, and prompt version."""
    __tablename__ = "answer_cache"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class PeerSet(Base):
    """A saved comps peer set for one deal: the SEC peers picked for a target, kept with their sources and
    refreshed on schedule (workflow kind `peer_refresh`). A peer that loses its revenue is dropped, never guessed."""
    __tablename__ = "peer_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    deal: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target_id: Mapped[int] = mapped_column(Integer)
    items: Mapped[str] = mapped_column(Text)  # JSON list of peers: cik, name, revenue, period, source_url, rule, matched_on
    dropped: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of {cik, name, reason} from the last refresh
    refreshed_at: Mapped[str] = mapped_column(String(40), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")


class TargetContact(Base):
    """A person at a target who may receive outreach. Only addresses a senior person added are ever mailed."""
    __tablename__ = "target_contact"
    __table_args__ = (UniqueConstraint("tenant_id", "target_id", "email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("target.id"), index=True)
    email: Mapped[str] = mapped_column(String(256))
    name: Mapped[str | None] = mapped_column(String(200), default=None)


class Person(Base):
    """An expert or contact the firm has used. Tied to a deal when it was sourced for one, so a walled deal's
    expert is hidden from keys that cannot see that deal."""
    __tablename__ = "person"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    organisation: Mapped[str | None] = mapped_column(String(200), default=None)
    title: Mapped[str | None] = mapped_column(String(200), default=None)
    expertise: Mapped[str | None] = mapped_column(Text, default=None)  # comma-separated topics
    deal: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    recorded_at: Mapped[str] = mapped_column(String(40), default="")


class OutreachItem(Base):
    """One outreach draft in the review queue. The text is frozen at queueing; sending re-drafts and refuses if it moved."""
    __tablename__ = "outreach_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("target.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | sent
    sender: Mapped[str] = mapped_column(String(120))
    firm: Mapped[str] = mapped_column(String(120))
    thesis: Mapped[str | None] = mapped_column(Text, default=None)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[str] = mapped_column(String(40), default="")
    sent_at: Mapped[str | None] = mapped_column(String(40), default=None)


class DigestPref(Base):
    """One signed-in person's alert digest: where it goes, the least severe alert it includes, and the last alert sent.
    Keyed on the OIDC subject, so a person's preference follows their account, not a shared key."""
    __tablename__ = "digest_pref"
    __table_args__ = (UniqueConstraint("tenant_id", "subject"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(256))
    min_severity: Mapped[str] = mapped_column(String(16), default="info")
    last_alert_id: Mapped[int] = mapped_column(default=0)


class Alert(Base):
    """An inbox item written by a watcher. dedupe_key makes repeated scans idempotent."""
    __tablename__ = "alert"
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(256))
    fact_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of fact ids
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    created_at: Mapped[str] = mapped_column(String(40), default="")
    emailed_at: Mapped[str | None] = mapped_column(String(40), default=None)
    deal: Mapped[str | None] = mapped_column(String(128), default=None, index=True)  # set when the alert is about a deal


class DealLink(Base):
    """Links a deal to its CRM record, with the stage each side had at the last stage sync (deal vocabulary)."""
    __tablename__ = "deal_link"
    __table_args__ = (UniqueConstraint("tenant_id", "connector", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    connector: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    deal: Mapped[str] = mapped_column(String(128))
    last_local: Mapped[str] = mapped_column(String(16))
    last_external: Mapped[str] = mapped_column(String(16))


class CalendarEvent(Base):
    """A meeting from a connected calendar. starts_at is the date (YYYY-MM-DD); board marks board meetings."""
    __tablename__ = "calendar_event"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[str] = mapped_column(String(10))
    url: Mapped[str] = mapped_column(Text, default="")
    company: Mapped[str | None] = mapped_column(String(256), default=None, index=True)
    board: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The deal whose name or alias the title names, when exactly one does (app/calendar_events.py)
    deal: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    body: Mapped[str] = mapped_column(Text, default="", server_default="")  # the meeting's text, capped by the connector


class Connection(Base):
    """A saved connector setup: options, deal wall, encrypted token and an optional sync interval."""
    __tablename__ = "connection"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    connector: Mapped[str] = mapped_column(String(32))
    deal: Mapped[str | None] = mapped_column(String(128), default=None)
    options: Mapped[str] = mapped_column(Text, default="{}")  # JSON of non-secret options
    token_sealed: Mapped[str] = mapped_column(Text)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    last_run: Mapped[str | None] = mapped_column(String(40), default=None)
    last_status: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[str] = mapped_column(String(64))


class LboRun(Base):
    """A saved LBO run: the cited request as sent, and the result it produced when saved. Kept so a run can be
    reopened and compared later without re-deriving inputs that may have changed since."""
    __tablename__ = "lbo_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")
    request: Mapped[str] = mapped_column(Text)  # JSON: the /lbo/returns body
    result: Mapped[str] = mapped_column(Text)  # JSON: the /lbo/returns response at save time


class RateWindow(Base):
    """Requests counted per tenant per minute, for the replica-shared rate limit. Rows are throwaway."""
    __tablename__ = "rate_window"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    minute: Mapped[int] = mapped_column(Integer, primary_key=True)
    n: Mapped[int] = mapped_column(Integer, default=0)

