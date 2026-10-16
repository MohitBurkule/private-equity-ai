from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Document, PageRow
from app.parse.pdf import extract_pages
from app.parse.xlsx import extract_sheets


def ingest_pdf(db: Session, path: Path, filename: str | None = None) -> Document:
    """Idempotent: same bytes (sha256) return the existing document."""
    pages = extract_pages(path)
    doc_id = pages[0].doc_id if pages else None
    if doc_id is None:
        raise ValueError("PDF has no pages")
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    doc = Document(id=doc_id, filename=filename or path.name, n_pages=len(pages))
    doc.pages = [PageRow(number=p.number, text=p.text) for p in pages]
    db.add(doc)
    db.commit()
    return doc


def ingest_bytes(db: Session, data: bytes, filename: str) -> Document:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "upload.pdf"
        p.write_bytes(data)
        return ingest_pdf(db, p, filename)


def ingest_xlsx(db: Session, path: Path, filename: str | None = None) -> Document:
    sheets = extract_sheets(path)
    if not sheets:
        raise ValueError("workbook has no sheets")
    doc_id = sheets[0].doc_id
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    doc = Document(id=doc_id, filename=filename or path.name, n_pages=len(sheets), kind="xlsx")
    doc.pages = [PageRow(number=s.number, text=s.text, label=s.name) for s in sheets]
    db.add(doc)
    db.commit()
    return doc


def ingest_upload(db: Session, data: bytes, filename: str) -> Document:
    """Dispatch on content, not extension: PDF magic or zip (xlsx) magic."""
    with tempfile.TemporaryDirectory() as d:
        if data[:4] == b"%PDF":
            p = Path(d) / "upload.pdf"
            p.write_bytes(data)
            return ingest_pdf(db, p, filename)
        if data[:2] == b"PK":
            p = Path(d) / "upload.xlsx"
            p.write_bytes(data)
            return ingest_xlsx(db, p, filename)
    raise ValueError("unsupported file type (expected PDF or XLSX)")
