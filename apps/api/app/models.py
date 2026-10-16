"""Core tables. A Fact cannot exist without a FactSource (citation is mandatory)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))


class ApiKey(Base):
    __tablename__ = "api_key"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, server_default="false")
    role: Mapped[str] = mapped_column(String(16), default="analyst", server_default="analyst")
    deals: Mapped[str | None] = mapped_column(Text, default=None)  # comma list; None = unrestricted


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
    pages: Mapped[list[PageRow]] = relationship(back_populates="document", cascade="all")


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
    sources: Mapped[list[FactSource]] = relationship(back_populates="fact", cascade="all")


class FactSource(Base):
    __tablename__ = "fact_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("fact.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    fact: Mapped[Fact] = relationship(back_populates="sources")


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


STAGES = ["sourcing", "screening", "dd", "ic", "signed", "closed", "passed"]


class Deal(Base):
    """A deal workspace: name, stage and note. Documents and DD items refer to it by name."""
    __tablename__ = "deal"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(16), default="sourcing")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[str] = mapped_column(String(40), default="")


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
