"""Strip personal identifiers from what leaves the system, when the tenant's PII flag is on.

Text goes through app.redact. Workbooks and Word or PowerPoint files are rewritten cell by cell and paragraph
by paragraph, so the layout and every figure stay as they were. Nothing else in a file is touched.
"""
from __future__ import annotations

import io

from sqlalchemy.orm import Session

from app.models import Tenant
from app.redact import redact


def pii_on(db: Session, tenant_id: str) -> bool:
    t = db.get(Tenant, tenant_id)
    return bool(t and t.pii_redaction)


def text(on: bool, s: str) -> str:
    return redact(s) if on else s


def xlsx(data: bytes) -> bytes:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.value = redact(cell.value)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _paragraph(p) -> None:
    """Redact at paragraph level, so an identifier split across runs is still caught. The text goes into the
    first run and the rest are emptied, which keeps the first run's formatting."""
    full = p.text
    clean = redact(full)
    if clean == full or not p.runs:
        return
    p.runs[0].text = clean
    for r in p.runs[1:]:
        r.text = ""


def docx(data: bytes) -> bytes:
    from docx import Document

    d = Document(io.BytesIO(data))
    paras = list(d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                paras += cell.paragraphs
    for p in paras:
        _paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def pptx(data: bytes) -> bytes:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    _paragraph(p)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            _paragraph(p)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
