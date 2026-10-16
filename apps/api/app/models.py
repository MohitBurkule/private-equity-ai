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


class Document(Base):
    __tablename__ = "document"
    # id = sha256(tenant_id:content_sha256): same file in two tenants never collides or leaks existence
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(512))
    n_pages: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="pdf")
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
    sources: Mapped[list[FactSource]] = relationship(back_populates="fact", cascade="all")


class FactSource(Base):
    __tablename__ = "fact_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("fact.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    fact: Mapped[Fact] = relationship(back_populates="sources")
