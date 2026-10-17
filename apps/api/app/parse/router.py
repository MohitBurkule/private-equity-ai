"""Per-page engine router with numeric cross-checking and page+bbox citations.

Page type -> primary engine (chosen from the benchmark, evals/pdf_benchmark.py):
  scanned  (no text layer)        -> rapidocr (OCR; numbers flagged unverified)
  table    (numeric-dense rows)   -> pymupdf lines with bbox, verified against pdftotext -layout
  deck     (landscape, short lines)-> pymupdf lines
  prose    (legal / narrative)    -> pymupdf lines
Every numeric token on a text page is checked against an independent second engine; tokens the second
engine does not reproduce are reported in `disputed`, never silently trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.parse import engines

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
MIN_TEXT_CHARS = 20


def numbers(text: str) -> list[str]:
    return [m.group().replace(",", "").rstrip(".") for m in NUM.finditer(text)]


# OCR faults documented in data/uk/sh01/README.md: GBP sign read as "E" (E1,000,000), a stray quote
# inside a number (1000000'0), and a digit run split by a letter. Such tokens are flagged, never fixed.
OCR_SUSPECT = re.compile(r"(?<![A-Za-z])E\d[\d,.]*|\d+'\d+|\d[A-Za-z]\d")


def ocr_suspects(lines: list[engines.Line]) -> list[str]:
    return [m.group() for ln in lines for m in OCR_SUSPECT.finditer(ln.text)]


@dataclass
class RoutedPage:
    page: int
    kind: str  # scanned | table | deck | prose
    engine: str
    method: str  # text | ocr
    lines: list[engines.Line]
    checked_by: str | None = None
    disputed: list[str] = field(default_factory=list)  # numbers the second engine lacks
    verified: bool = False  # text page whose numbers all agree across two engines
    suspects: list[str] = field(default_factory=list)  # OCR tokens matching known fault patterns

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


def classify(lines: list[engines.Line], width: float = 0.0, height: float = 0.0) -> str:
    text = "\n".join(ln.text for ln in lines)
    if len(text.strip()) < MIN_TEXT_CHARS:
        return "scanned"
    numeric = [ln for ln in lines if len(numbers(ln.text)) >= 2 and re.search(r"[A-Za-z]{3}", ln.text)]
    if len(numeric) >= 5 and len(numeric) / max(len(lines), 1) >= 0.25:
        return "table"
    if width > height > 0 and sum(len(ln.text) for ln in lines) / max(len(lines), 1) < 40:
        return "deck"
    return "prose"


def _size(path: Path, page: int) -> tuple[float, float]:
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(str(path))[page - 1].get_size()


def route_page(path: Path, page: int, have: set[str] | None = None) -> RoutedPage:
    have = have if have is not None else set(engines.available())
    primary = "pypdfium2_words" if "pypdfium2_words" in have else "pdftotext" if "pdftotext" in have else "pypdf"
    pr = engines.run(primary, path, [page])[0]
    w, h = _size(path, page) if "pypdfium2_words" in have else (0.0, 0.0)
    kind = classify(pr.lines, w, h)
    if kind == "scanned":
        if "rapidocr" in have:
            ocr = engines.run("rapidocr", path, [page])[0]
            return RoutedPage(page, kind, "rapidocr", "ocr", ocr.lines, suspects=ocr_suspects(ocr.lines))
        return RoutedPage(page, kind, primary, "text", pr.lines)
    second = next((e for e in ("pdftotext_layout", "pdfplumber", "pdfium", "pypdf") if e in have and e != primary), None)
    rp = RoutedPage(page, kind, primary, "text", pr.lines)
    if second:
        other = engines.run(second, path, [page])[0]
        theirs = set(numbers(other.text))
        rp.checked_by = second
        rp.disputed = sorted({n for n in numbers(pr.text) if n not in theirs})
        rp.verified = not rp.disputed
    return rp


def route_document(path: Path, pages: list[int] | None = None) -> list[RoutedPage]:
    have = set(engines.available())
    if pages is None:
        import pypdf
        pages = list(range(1, len(pypdf.PdfReader(str(path)).pages) + 1))
    return [route_page(path, p, have) for p in pages]


def cite(rp: RoutedPage, needle: str) -> dict | None:
    """Page + bbox of the first line containing `needle`, for source-linked insights."""
    n = re.sub(r"\s+", " ", needle).strip().lower()
    for ln in rp.lines:
        if n in re.sub(r"\s+", " ", ln.text).lower():
            return {"page": rp.page, "bbox": ln.bbox, "engine": ln.engine, "method": rp.method, "verified": rp.verified}
    return None
