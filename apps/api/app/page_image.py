"""Render one PDF page as it was filed, with the cited quote highlighted.

A reader checks a number against the page image, not against extracted text, so the highlight
marks where the quote sits on the page. If the quote cannot be found on the page, the page is
returned without a highlight and the caller says so.
"""
from __future__ import annotations

import pymupdf

ZOOM = 1.6
_MIN_SEARCH = 12  # shorter fragments match too much of the page to mark a quote


def render_page(pdf: bytes, number: int, quote: str) -> tuple[bytes, bool]:
    """PNG bytes for page `number` (1-based) and whether the quote was found and highlighted."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[number - 1]
        rects = _quote_rects(page, quote)
        for r in rects:
            page.add_highlight_annot(r)
        png = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).tobytes("png")
    return png, bool(rects)


def _quote_rects(page: pymupdf.Page, quote: str) -> list[pymupdf.Rect]:
    text = " ".join(quote.split())
    if not text:
        return []
    found = page.search_for(text)
    if found:
        return found
    # A quote that runs past the printed text (a wrapped line, a stray glyph) may still match its
    # leading words; drop trailing words until a long enough prefix is on the page.
    words = text.split()
    for n in range(len(words) - 1, 0, -1):
        head = " ".join(words[:n])
        if len(head) < _MIN_SEARCH:
            break
        found = page.search_for(head)
        if found:
            return _same_line_tokens(page, found, set(text.split()))
    return []


def _same_line_tokens(page: pymupdf.Page, found: list[pymupdf.Rect], tokens: set[str]) -> list[pymupdf.Rect]:
    """Table rows print the rest of a quote across columns; mark the quote's words on the matched line."""
    out = list(found)
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        if word in tokens and any(y0 < r.y1 and y1 > r.y0 for r in found):
            out.append(pymupdf.Rect(x0, y0, x1, y1))
    return out
