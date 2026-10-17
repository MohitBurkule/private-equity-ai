from __future__ import annotations

import csv
import hashlib
import io
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.html_doc import parse_units
from app.ixbrl import read_ixbrl
from app.ixbrl_full import read_filing
from app.models import Document, DocumentFile, HtmlUnit, PageRow
from app.parse.eml import parse_eml
from app.parse.office import RawPage, extract_docx, extract_pptx
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
    if rep.pnl:
        lines.append(f"P&L for {rep.pnl_period} (as tagged, not checked)")
        lines += [f"{k}: {v:,}" for k, v in sorted(rep.pnl.items())]
    else:
        lines.append("[no P&L tagged in this filing: revenue, gross profit and operating profit unverified]")
    if not rep.facts:
        lines.append("[no balance-sheet figures found in this filing]")
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename, n_pages=1, kind="ixbrl")
    doc.pages = [PageRow(number=1, text="\n".join(lines), label=rep.instant)]
    db.add(doc)
    db.commit()
    return doc


def ingest_ixbrl_filing(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    """Full inline-XBRL 10-K/10-Q as filed: every page of visible text, so a figure can be quoted
    from the page a reader turns to. Small UK accounts keep the headline-only path above."""
    pages, _ = read_filing(data.decode("utf-8", errors="replace"))
    if not pages:
        raise ValueError("iXBRL filing has no visible text")
    return _store_pages(db, tenant_id, data, filename, "ixbrl", pages)


ROWS_PER_PAGE = 50
MAX_CSV_ROWS = 200_000


def ingest_csv(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    """CSV/TSV (e.g. a platform account export a user downloads): rows become cell-like lines
    `row 7: Header=value | Header=value`, 50 rows per page, so facts can cite a row. No platform
    column layout is assumed. Excel formula-injection prefixes are kept as plain text."""
    sha = hashlib.sha256(data).hexdigest()
    doc_id = tenant_doc_id(tenant_id, sha)
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError("CSV needs a header row and at least one data row with 2+ columns")
    if len(rows) - 1 > MAX_CSV_ROWS:
        raise ValueError(f"CSV has more than {MAX_CSV_ROWS} rows")
    head = [h.strip() or f"col{i + 1}" for i, h in enumerate(rows[0])]
    lines = []
    for n, r in enumerate(rows[1:], 1):
        cells = [f"{head[i] if i < len(head) else f'col{i + 1}'}={v.strip()}" for i, v in enumerate(r)
                 if v.strip()]
        lines.append(f"row {n}: " + " | ".join(cells))
    chunks = [lines[i:i + ROWS_PER_PAGE] for i in range(0, len(lines), ROWS_PER_PAGE)]
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename, n_pages=len(chunks),
                   kind="csv")
    doc.pages = [PageRow(number=i, text="Columns: " + " | ".join(head) + "\n" + "\n".join(c),
                         label=f"rows {(i - 1) * ROWS_PER_PAGE + 1}-{(i - 1) * ROWS_PER_PAGE + len(c)}")
                 for i, c in enumerate(chunks, 1)]
    db.add(doc)
    db.commit()
    return doc


def _keep_original(db: Session, tenant_id: str, doc_id: str, data: bytes,
                   media_type: str = "application/pdf") -> None:
    if db.get(DocumentFile, doc_id) is None:
        db.add(DocumentFile(document_id=doc_id, tenant_id=tenant_id, data=data, media_type=media_type))
        db.commit()


def ingest_upload(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    """Dispatch on content, not extension: PDF magic or zip (xlsx) magic."""
    with tempfile.TemporaryDirectory() as d:
        if data[:4] == b"%PDF":
            p = Path(d) / "upload.pdf"
            p.write_bytes(data)
            doc = ingest_pdf(db, tenant_id, p, filename)
            _keep_original(db, tenant_id, doc.id, data)
            return doc
        if data[:2] == b"PK":
            p = Path(d) / "upload.xlsx"
            p.write_bytes(data)
            return ingest_xlsx(db, tenant_id, p, filename)
    if b"ix:nonfraction" in data[:2_000_000].lower():
        # Filings carry page-break styles; small UK accounts do not.
        if b"page-break" in data.lower():
            doc = ingest_ixbrl_filing(db, tenant_id, data, filename)
            _keep_original(db, tenant_id, doc.id, data, "text/html")
            return doc
        return ingest_ixbrl(db, tenant_id, data, filename)
    if filename.lower().endswith((".csv", ".tsv")):
        return ingest_csv(db, tenant_id, data, filename)
    if b"<html" in data[:2_000_000].lower() or b"<!doctype html" in data[:2_000].lower():
        return ingest_html_doc(db, tenant_id, data, filename)
    raise ValueError("unsupported file type (expected PDF, XLSX, CSV, HTML or iXBRL HTML)")


def ingest_html_doc(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    """Plain HTML (a credit agreement exhibit, say). Stored as text blocks with section and anchor, not pages."""
    sha = hashlib.sha256(data).hexdigest()
    doc_id = tenant_doc_id(tenant_id, sha)
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    units = parse_units(data)
    if not units:
        raise ValueError("no text found")
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename, n_pages=0, kind="html")
    db.add(doc)
    db.add_all(HtmlUnit(tenant_id=tenant_id, document_id=doc_id, idx=u.idx, section=u.section, heading=u.heading,
                        anchor=u.anchor, offset=u.offset, text=u.text) for u in units)
    db.commit()
    # Kept as filed so the citation viewer can highlight the block at its offset.
    _keep_original(db, tenant_id, doc_id, data, media_type="text/html")
    return doc


def _store_pages(db: Session, tenant_id: str, data: bytes, filename: str, kind: str,
                 pages: list[RawPage]) -> Document:
    """Idempotent store of text pages for non-PDF office/email content."""
    sha = hashlib.sha256(data).hexdigest()
    doc_id = tenant_doc_id(tenant_id, sha)
    existing = db.get(Document, doc_id)
    if existing:
        return existing
    if not pages:
        raise ValueError("no text found")
    doc = Document(id=doc_id, tenant_id=tenant_id, sha256=sha, filename=filename, n_pages=len(pages), kind=kind)
    doc.pages = [PageRow(number=i, text=p.text, label=p.label) for i, p in enumerate(pages, 1)]
    db.add(doc)
    db.commit()
    return doc


def ingest_docx(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    return _store_pages(db, tenant_id, data, filename, "docx", extract_docx(data))


def ingest_pptx(db: Session, tenant_id: str, data: bytes, filename: str) -> Document:
    return _store_pages(db, tenant_id, data, filename, "pptx", extract_pptx(data))


MAX_ARCHIVE_FILES = 2000
MAX_ARCHIVE_BYTES = int(os.environ.get("MAX_ARCHIVE_UNCOMPRESSED_BYTES", str(1024**3)))
MAX_DEPTH = 3
_JUNK = ("__MACOSX/", ".DS_Store", "Thumbs.db", "~$")


@dataclass
class IngestResult:
    documents: list[Document] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"name":..., "reason":...}: never silent


def _zip_kind(data: bytes) -> str:
    """Office files are zips: tell them apart by their content types, not the extension."""
    try:
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return "bad"
    if "[Content_Types].xml" in names:
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
    return "archive"


def _looks_like_email(data: bytes) -> bool:
    head = data[:4096].lower()
    return head.startswith((b"from:", b"received:", b"return-path:", b"mime-version:", b"date:")) and b"\nsubject:" in head


def ingest_any(db: Session, tenant_id: str, data: bytes, filename: str, _depth: int = 0) -> IngestResult:
    """Single entry for data-room uploads. Archives and emails expand into several documents whose
    names keep the folder path (`folder/sub/file.pdf`, `msg.eml/attachment.pdf`). Anything not
    ingested is reported in `skipped` with a reason."""
    res = IngestResult()
    low = filename.lower()
    try:
        if data[:2] == b"PK":
            kind = _zip_kind(data)
            if kind == "docx":
                res.documents.append(ingest_docx(db, tenant_id, data, filename))
            elif kind == "pptx":
                res.documents.append(ingest_pptx(db, tenant_id, data, filename))
            elif kind == "xlsx":
                with tempfile.TemporaryDirectory() as d:
                    p = Path(d) / "upload.xlsx"
                    p.write_bytes(data)
                    res.documents.append(ingest_xlsx(db, tenant_id, p, filename))
            elif kind == "archive":
                _ingest_archive(db, tenant_id, data, filename, res, _depth)
            else:
                res.skipped.append({"name": filename, "reason": "corrupt zip file"})
        elif low.endswith(".eml") or _looks_like_email(data):
            pe = parse_eml(data)
            res.documents.append(_store_pages(db, tenant_id, data, filename, "email", [RawPage(pe.text, "message")]))
            for name, payload in pe.attachments:
                sub = ingest_any(db, tenant_id, payload, f"{filename}/{name}", _depth + 1)
                res.documents += sub.documents
                res.skipped += sub.skipped
        else:
            res.documents.append(ingest_upload(db, tenant_id, data, filename))
    except Exception as e:  # noqa: BLE001  one bad file must not sink the batch
        db.rollback()
        res.skipped.append({"name": filename, "reason": f"cannot parse: {e}"})
    return res


def _ingest_archive(db: Session, tenant_id: str, data: bytes, filename: str, res: IngestResult,
                    depth: int) -> None:
    if depth >= MAX_DEPTH:
        res.skipped.append({"name": filename, "reason": f"archive nested deeper than {MAX_DEPTH}"})
        return
    zf = zipfile.ZipFile(io.BytesIO(data))
    infos = [i for i in zf.infolist() if not i.is_dir() and not any(j in i.filename for j in _JUNK)]
    if len(infos) > MAX_ARCHIVE_FILES:
        res.skipped.append({"name": filename, "reason": f"more than {MAX_ARCHIVE_FILES} files"})
        return
    if sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:  # declared sizes; also bounded per read below
        res.skipped.append({"name": filename, "reason": "uncompressed size over limit (zip bomb guard)"})
        return
    for info in infos:
        name = info.filename.lstrip("/")
        if ".." in Path(name).parts:
            res.skipped.append({"name": name, "reason": "path escapes archive"})
            continue
        if info.flag_bits & 0x1:
            res.skipped.append({"name": name, "reason": "encrypted"})
            continue
        with zf.open(info) as f:
            payload = f.read(info.file_size + 1)
        if len(payload) > info.file_size:  # header lied about size
            res.skipped.append({"name": name, "reason": "size mismatch (corrupt or hostile)"})
            continue
        sub = ingest_any(db, tenant_id, payload, f"{filename}/{name}" if depth else name, depth + 1)
        res.documents += sub.documents
        res.skipped += sub.skipped


def finalize_upload(db: Session, who, res: IngestResult, deal: str | None) -> tuple[list[Document], list[dict]]:
    """Apply the deal tag and the caller's wall to freshly ingested documents (shared by the
    synchronous endpoint and the background worker)."""
    from app.acl import doc_visible, hidden_deal_names
    kept: list[Document] = []
    skipped = list(res.skipped)
    for doc in {d.id: d for d in res.documents}.values():  # same bytes twice in one upload = once
        if doc.deal is None and deal:
            doc.deal = deal
        elif deal and doc.deal != deal:
            skipped.append({"name": doc.filename, "reason": "identical content already stored under a different deal"})
            continue
        if not doc_visible(doc, who, hidden_deal_names(db, who)):
            skipped.append({"name": doc.filename, "reason": "identical content already stored outside this key's scope"})
            continue
        kept.append(doc)
    db.commit()
    return kept, skipped
