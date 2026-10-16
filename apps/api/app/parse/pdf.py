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


def extract_pages(path: Path) -> list[Page]:
    doc_id = doc_id_for(path)
    reader = PdfReader(str(path))
    return [Page(doc_id, i, _page_text(p)) for i, p in enumerate(reader.pages, 1)]
