"""Fact creation gate: a fact is stored only if its citation verifies in code."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.citations import quote_in_page, verify_number
from app.models import Document, Fact, FactSource, PageRow


class CitationError(ValueError):
    pass


def add_verified_fact(
    db: Session, *, tenant_id: str, entity: str, metric: str, period: str, value: Decimal, unit: str,
    document_id: str, page: int, quote: str, scale: Decimal = Decimal(1), basis: str = "GAAP",
) -> Fact:
    """value is in `unit` AFTER applying scale to the printed number(s) in the quote."""
    doc = db.get(Document, document_id)
    row = (db.query(PageRow).filter_by(document_id=document_id, number=page).one_or_none()
           if doc is not None and doc.tenant_id == tenant_id else None)
    if row is None:
        raise CitationError(f"page {page} not found in document {document_id[:8]}")
    if not quote_in_page(quote, row.text):
        raise CitationError("quote not found on cited page")
    if not verify_number(value, quote, scale):
        raise CitationError("value does not match any number in the quote")
    fact = Fact(tenant_id=tenant_id, entity=entity, metric=metric, period=period, value=value, unit=unit,
                basis=basis, status="verified")
    fact.sources = [FactSource(document_id=document_id, page=page, quote=quote)]
    db.add(fact)
    db.commit()
    return fact
