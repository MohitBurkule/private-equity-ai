from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.ixbrl import read_ixbrl
from app.models import Document, PageRow
from app.parse.pdf import extract_pages
from app.parse.xlsx import extract_sheets


def tenant_doc_id(tenant_id: str, content_sha: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{content_sha}".encode()).hexdigest()


def ingest_pdf(db: Session, tenant_id: str, path: Path, filename: str | None = None) -> Document:
    """Idempotent: same bytes (sha256) return the existing document."""
    pages = extract_pages(path, ocr=os.environ.get("OCR_ENABLED", "") == "1")
    if not pages:
        raise ValueError("PDF has no pages")
    sha = pages[0].doc_id
    doc_id = tenant_doc_id(tenant_id, sha)
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename or path.name,
                   n_pages=len(pages))
    doc.pages = [PageRow(number=p.number, text=p.text, method=p.method, ocr_confidence=p.confidence)
                 for p in pages]
    db.add(doc)
    db.commit()
    return doc


def ingest_xlsx(db: Session, tenant_id: str, path: Path, filename: str | None = None) -> Document:
    sheets = extract_sheets(path)
    if not sheets:
        raise ValueError("workbook has no sheets")
    sha = sheets[0].doc_id
    doc_id = tenant_doc_id(tenant_id, sha)
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename or path.name,
                   n_pages=len(sheets), kind="xlsx")
    doc.pages = [PageRow(number=s.number, text=s.text, label=s.name) for s in sheets]
    db.add(doc)
    db.commit()
    return doc


def ingest_ixbrl(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    """UK iXBRL accounts: one page of headline balance-sheet lines. A failing identity puts an
    UNRELIABLE banner at the top of the page so it travels with every quote and answer."""
    sha = hashlib.sha256(data).hexdigest()
    doc_id = tenant_doc_id(tenant_id, sha)
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    rep = read_ixbrl(data.decode("utf-8", errors="replace"))
    lines = []
    if not rep.reliable:
        failed = ", ".join(k for k, v in rep.checks.items() if v is False)
        lines.append(f"[UNRELIABLE: balance sheet fails internal arithmetic ({failed}); do not rely on figures]")
    if rep.instant:
        lines.append(f"Balance sheet at {rep.instant}")
    lines += [f"{k}: {v:,}" for k, v in sorted(rep.facts.items())]
    if not rep.facts:
        lines.append("[no balance-sheet figures found in this filing]")
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename, n_pages=1, kind="ixbrl")
    doc.pages = [PageRow(number=1, text="\n".join(lines), label=rep.instant)]
    db.add(doc)
    db.commit()
    return doc


def ingest_upload(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    """Dispatch on content, not extension: PDF magic or zip (xlsx) magic."""
    with tempfile.TemporaryDirectory() as d:
        if data[:4] == b"%PDF":
            p = Path(d) / "upload.pdf"
            p.write_bytes(data)
            return ingest_pdf(db, tenant_id, p, filename)
        if data[:2] == b"PK":
            p = Path(d) / "upload.xlsx"
            p.write_bytes(data)
            return ingest_xlsx(db, tenant_id, p, filename)
    if b"ix:nonfraction" in data[:2_000_000].lower():
        return ingest_ixbrl(db, tenant_id, data, filename)
    raise ValueError("unsupported file type (expected PDF, XLSX or iXBRL HTML)")
