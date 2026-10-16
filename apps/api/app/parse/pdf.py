"""Page-level PDF text extraction with stable 1-based page numbers.

Permissive-licence only (pypdf). Heavier layout/OCR parsers plug in behind the
same Page interface (see docs/ARCHITECTURE.md section 4).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Page:
    doc_id: str
    number: int  # 1-based
    text: str
    method: str = "text"  # text | ocr
    confidence: float | None = None  # OCR mean confidence


def doc_id_for(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _page_text(page) -> str:
    """Layout mode keeps table rows on one line; fall back for pages it cannot handle
    (e.g. blank pages without /Contents raise KeyError in pypdf)."""
    for mode in ("layout", "plain"):
        try:
            return page.extract_text(extraction_mode=mode) or ""
        except Exception as e:  # noqa: BLE001  parser edge cases; callers see empty text
            log.warning("page text extraction failed in %s mode: %r", mode, e)
    return ""


MIN_TEXT_CHARS = 20


def extract_pages(path: Path, ocr: bool = False) -> list[Page]:
    """ocr=True runs OCR on pages with (almost) no text layer. Never silent: such pages are
    marked method="ocr" with a confidence; if OCR is unavailable they stay empty and method="text"."""
    doc_id = doc_id_for(path)
    reader = PdfReader(str(path))
    pages = []
    for i, p in enumerate(reader.pages, 1):
        text = _page_text(p)
        if ocr and len(text.strip()) < MIN_TEXT_CHARS:
            from app.parse import ocr as ocr_mod
            if ocr_mod.available():
                t, conf = ocr_mod.ocr_page(path, i - 1)
                pages.append(Page(doc_id, i, t, "ocr", conf))
                continue
            log.warning("page %d has no text layer and OCR is not installed", i)
        pages.append(Page(doc_id, i, text))
    return pages
