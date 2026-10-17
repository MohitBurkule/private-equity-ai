"""Fact creation gate: a fact is stored only if its citation verifies in code."""
from __future__ import annotations

import re
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.citations import quote_in_page, verify_number, xlsx_location
from app.models import Document, DocumentFile, Fact, FactSource, HtmlUnit, PageRow
from app.parse import engines

# Labels for money paid out. Their tables print the amount in parentheses, so a positive claim
# is the same figure, not a sign error.
_OUTFLOW = re.compile(r"capex|capital.?expend|purchase|repay|payment|dividend|distribution|buyback|"
                      r"repurchase|acquisition|outflow|paid", re.IGNORECASE)


class CitationError(ValueError):
    pass


def is_outflow(metric: str) -> bool:
    return bool(_OUTFLOW.search(metric))


def make_source(doc: Document, page: int, quote: str, row: PageRow) -> FactSource:
    """The citation for a quote on a page. Workbooks cite a cell, so the quote must start with its sheet and
    address, and that sheet must be the one this page holds; a page of text cannot say where a figure sits."""
    if doc.kind != "xlsx":
        return FactSource(document_id=doc.id, page=page, quote=quote)
    loc = xlsx_location(quote)
    if loc is None:
        raise CitationError("workbook quote must start with its cell, e.g. 'P&L!C14: 1,000'")
    sheet, cell, rowlabel = loc
    if row.label != sheet:
        raise CitationError("quote names a different sheet than the page cited")
    return FactSource(document_id=doc.id, page=page, quote=quote, kind="xlsx", heading=sheet, anchor=cell,
                      section=rowlabel)


def _layout_text(db: Session, document_id: str, page: int) -> str | None:
    """The page as poppler -layout prints it, from the kept PDF bytes. None when there is no PDF to read."""
    f = db.get(DocumentFile, document_id)
    if f is None or f.media_type != "application/pdf":
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.pdf"
        path.write_bytes(f.data)
        if "pdftotext_layout" not in engines.available():
            return None
        return engines.run("pdftotext_layout", path, [page])[0].text


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
    layout_only = False
    if not quote_in_page(quote, row.text):
        # The text layer can split a table row across lines. The layout text keeps it on one line, so a
        # quote found there is a text-only hit: no bbox, and it goes to the review queue, never auto-verified.
        if not quote_in_page(quote, _layout_text(db, document_id, page) or ""):
            raise CitationError("quote not found on cited page")
        layout_only = True
    if not verify_number(value, quote, scale, outflow=is_outflow(metric)):
        raise CitationError("value does not match any number in the quote")
    fact = Fact(tenant_id=tenant_id, entity=entity, metric=metric, period=period, value=value, unit=unit,
                basis=basis,
                status="ocr_unverified" if row.method == "ocr" or layout_only else "verified")
    fact.sources = [make_source(doc, page, quote, row)]
    db.add(fact)
    db.commit()
    return fact


def add_html_fact(
    db: Session, *, tenant_id: str, entity: str, metric: str, period: str, value: Decimal, unit: str,
    document_id: str, sources: list[tuple[int, str]], scale: Decimal = Decimal(1), basis: str = "GAAP",
) -> Fact:
    """HTML counterpart of add_verified_fact. sources: (unit idx, quote) pairs. The first one carries the
    figure; every source quote must appear in its own text block, so a defined-term chain is cited sentence
    by sentence. The value must match a number in the first quote."""
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id or not sources:
        raise CitationError("document not found")
    rows = {}
    for idx, quote in sources:
        row = db.query(HtmlUnit).filter_by(document_id=document_id, idx=idx).one_or_none()
        if row is None:
            raise CitationError(f"block {idx} not found in document {document_id[:8]}")
        if not quote_in_page(quote, row.text):
            raise CitationError("quote not found in cited block")
        rows[idx] = row
    _, first_quote = sources[0]
    if not verify_number(value, first_quote, scale, outflow=is_outflow(metric)):
        raise CitationError("value does not match any number in the quote")
    fact = Fact(tenant_id=tenant_id, entity=entity, metric=metric, period=period, value=value, unit=unit,
                basis=basis, status="verified")
    fact.sources = [FactSource(document_id=document_id, page=0, quote=quote, kind="html",
                               section=rows[idx].section, heading=rows[idx].heading, anchor=rows[idx].anchor,
                               offset=rows[idx].offset)
                    for idx, quote in sources]
    db.add(fact)
    db.commit()
    return fact


def add_chart_fact(
    db: Session, *, tenant_id: str, entity: str, metric: str, period: str, value: Decimal, unit: str,
    document_id: str, page: int, label: str, bbox: tuple[float, float, float, float],
) -> Fact:
    """A value read off a chart (vision model, matched to OCR of the chart). Always ocr_unverified: a chart
    is never trusted on its own, so only a human review_fact call can promote it. Cites page and label bbox."""
    doc = db.get(Document, document_id)
    row = (db.query(PageRow).filter_by(document_id=document_id, number=page).one_or_none()
           if doc is not None and doc.tenant_id == tenant_id else None)
    if row is None:
        raise CitationError(f"page {page} not found in document {document_id[:8]}")
    if not verify_number(value, label, outflow=is_outflow(metric)):
        raise CitationError("chart label does not match the value")
    fact = Fact(tenant_id=tenant_id, entity=entity, metric=metric, period=period, value=value, unit=unit,
                status="ocr_unverified")
    anchor = "bbox:" + ",".join(f"{x:.1f}" for x in bbox)
    fact.sources = [FactSource(document_id=document_id, page=page, quote=label, anchor=anchor)]
    db.add(fact)
    db.commit()
    return fact


def review_fact(db: Session, fact: Fact, *, action: str, reviewer: str, note: str | None = None,
                value: Decimal | None = None, page: int | None = None, quote: str | None = None,
                scale: Decimal = Decimal(1)) -> Fact:
    """Human review. accept: confirm (also lifts ocr_unverified). reject: keep the row, exclude from
    memos. edit: replace value and/or citation, but the new pair must pass the same gate as creation."""
    if action not in ("accept", "reject", "edit"):
        raise CitationError("action must be accept, reject or edit")
    src = fact.sources[0]
    if action == "edit":
        new_page = page if page is not None else src.page
        new_quote = quote if quote is not None else src.quote
        new_value = value if value is not None else fact.value
        doc = db.get(Document, src.document_id)
        if doc.kind == "html":
            # For HTML the number is the text block's index; the citation is that block's locator.
            row = db.query(HtmlUnit).filter_by(document_id=src.document_id, idx=new_page).one_or_none()
            if row is None:
                raise CitationError(f"block {new_page} not found in the cited document")
            if not quote_in_page(new_quote, row.text):
                raise CitationError("quote not found in cited block")
            fresh = FactSource(document_id=doc.id, page=0, quote=new_quote, kind="html", section=row.section,
                               heading=row.heading, anchor=row.anchor, offset=row.offset)
        else:
            row = db.query(PageRow).filter_by(document_id=src.document_id, number=new_page).one_or_none()
            if row is None:
                raise CitationError(f"page {new_page} not found in the cited document")
            if not quote_in_page(new_quote, row.text):
                raise CitationError("quote not found on cited page")
            fresh = make_source(doc, new_page, new_quote, row)
        if not verify_number(new_value, new_quote, scale, outflow=is_outflow(fact.metric)):
            raise CitationError("value does not match any number in the quote")
        fact.value, src.page, src.quote = new_value, fresh.page, new_quote
        src.kind, src.heading, src.anchor, src.section = fresh.kind, fresh.heading, fresh.anchor, fresh.section
        src.offset = fresh.offset
    fact.status = "rejected" if action == "reject" else "verified"
    fact.reviewed_by, fact.reviewed_at, fact.review_note = reviewer, datetime.now(UTC).isoformat(), note
    db.commit()
    return fact
