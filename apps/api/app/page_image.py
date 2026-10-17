"""Render one PDF page as it was filed, with the cited quote highlighted.

A reader checks a number against the page image, not against extracted text, so the highlight
marks where the quote sits on the page. If the quote cannot be found on the page, the page is
returned without a highlight and the caller says so.

Rendering uses PDFium (Apache-2.0/BSD) rather than PyMuPDF, which is AGPL-3.0 unless bought
under its commercial licence; the highlight is drawn over the bitmap, not as a PDF annotation.
"""
from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

ZOOM = 1.6
_MIN_SEARCH = 12  # shorter fragments match too much of the page to mark a quote
_HIGHLIGHT = (255, 230, 0, 110)

# left, top, right, bottom in PDF points with the origin at the top-left, as the bitmap is laid out
Box = tuple[float, float, float, float]


def render_page(pdf: bytes, number: int, quote: str) -> tuple[bytes, bool]:
    """PNG bytes for page `number` (1-based) and whether the quote was found and highlighted."""
    doc = pdfium.PdfDocument(pdf)
    try:
        page = doc[number - 1]
        height = page.get_height()
        textpage = page.get_textpage()
        try:
            boxes = _quote_boxes(textpage, height, quote)
            image = page.render(scale=ZOOM).to_pil().convert("RGBA")
            if boxes:
                overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                for left, top, right, bottom in boxes:
                    draw.rectangle([left * ZOOM, top * ZOOM, right * ZOOM, bottom * ZOOM], fill=_HIGHLIGHT)
                image = Image.alpha_composite(image, overlay)
            out = io.BytesIO()
            image.convert("RGB").save(out, format="PNG")
        finally:
            textpage.close()
    finally:
        doc.close()
    return out.getvalue(), bool(boxes)


def _quote_boxes(textpage: pdfium.PdfTextPage, height: float, quote: str) -> list[Box]:
    text = " ".join(quote.split())
    if not text:
        return []
    found = _search(textpage, height, text)
    if found:
        return found
    # A quote that runs past the printed text (a wrapped line, a stray glyph) may still match its
    # leading words; drop trailing words until a long enough prefix is on the page.
    words = text.split()
    for n in range(len(words) - 1, 0, -1):
        head = " ".join(words[:n])
        if len(head) < _MIN_SEARCH:
            break
        found = _search(textpage, height, head)
        if found:
            return _same_line_tokens(textpage, height, found, set(words))
    return []


def _search(textpage: pdfium.PdfTextPage, height: float, text: str) -> list[Box]:
    out: list[Box] = []
    searcher = textpage.search(text)
    try:
        hit = searcher.get_next()
        while hit is not None:
            index, count = hit
            out.extend(_run_boxes(textpage, height, index, count))
            hit = searcher.get_next()
    finally:
        searcher.close()
    return out


def _run_boxes(textpage: pdfium.PdfTextPage, height: float, index: int, count: int) -> list[Box]:
    """One box per printed line of a character run, so a wrapped quote gets a box per line."""
    boxes: list[Box] = []
    for i in range(index, index + count):
        box = _char_box(textpage, height, i)
        if box is None:
            continue
        if boxes and _shares_line(boxes[-1], box):
            boxes[-1] = _union(boxes[-1], box)
        else:
            boxes.append(box)
    return boxes


def _char_box(textpage: pdfium.PdfTextPage, height: float, index: int) -> Box | None:
    left, bottom, right, top = textpage.get_charbox(index)
    if right <= left or top <= bottom:
        return None  # generated or zero-width glyphs have nothing to mark
    return (left, height - top, right, height - bottom)


def _same_line_tokens(textpage: pdfium.PdfTextPage, height: float, found: list[Box], tokens: set[str]) -> list[Box]:
    """Table rows print the rest of a quote across columns; mark the quote's words on the matched line."""
    out = list(found)
    for word, box in _words(textpage, height):
        if word in tokens and any(_shares_line(box, r) for r in found):
            out.append(box)
    return out


def _words(textpage: pdfium.PdfTextPage, height: float) -> list[tuple[str, Box]]:
    text = textpage.get_text_range()
    words: list[tuple[str, Box]] = []
    current: list[str] = []
    box: Box | None = None
    for i, ch in enumerate(text):
        glyph = _char_box(textpage, height, i)
        if ch.isspace() or glyph is None:
            if current and box is not None:
                words.append(("".join(current), box))
            current, box = [], None
            continue
        current.append(ch)
        box = glyph if box is None else _union(box, glyph)
    if current and box is not None:
        words.append(("".join(current), box))
    return words


def _shares_line(a: Box, b: Box) -> bool:
    return a[1] < b[3] and a[3] > b[1]


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
