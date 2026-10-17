"""Chart value extraction, option B: no VLM. Finds chart pictures with Docling, renders each picture
region, and OCRs its labels (axis ticks, bar/point value labels). Every value keeps the page and the
bbox of the label it came from, so the citation points at the chart, not at a guess.

Values here are labels printed on the chart, never estimates read off bar heights.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NUM = re.compile(r"^\(?-?\$?£?€?\d[\d,]*(?:\.\d+)?%?\)?$")


@dataclass(frozen=True)
class ChartValue:
    page: int
    text: str
    value: float
    bbox: tuple[float, float, float, float]  # PDF points, top-left origin
    conf: float | None


def chart_regions(path: Path, page: int) -> list[tuple[float, float, float, float]]:
    """Picture bboxes from Docling's layout model (top-left origin, PDF points)."""
    from docling.document_converter import DocumentConverter
    doc = DocumentConverter().convert(str(path), page_range=(page, page)).document
    out = []
    for pic, _ in doc.iterate_items():
        if type(pic).__name__ != "PictureItem":
            continue
        for prov in pic.prov or []:
            b = prov.bbox
            h = doc.pages[prov.page_no].size.height
            if b.coord_origin.name == "BOTTOMLEFT":
                out.append((b.l, h - b.t, b.r, h - b.b))
            else:
                out.append((b.l, b.t, b.r, b.b))
    return out


def parse_number(text: str) -> float | None:
    t = text.strip()
    if not NUM.match(t):
        return None
    neg = t.startswith(("(", "-"))
    digits = re.sub(r"[^\d.]", "", t)
    if not digits or digits == ".":
        return None
    v = float(digits)
    return -v if neg else v


def read_region(path: Path, page: int, box: tuple[float, float, float, float], scale: float = 3.0) -> list[ChartValue]:
    """OCR one picture region and return numeric labels with absolute page bboxes."""
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    global _ocr
    _ocr = _ocr or RapidOCR()
    x0, y0, x1, y1 = box
    pg = pdfium.PdfDocument(str(path))[page - 1]
    w, h = pg.get_size()
    # pdfium crop is inward margins (left, bottom, right, top) in points, not a rectangle
    img = pg.render(scale=scale, crop=(x0, h - y1, w - x1, y0)).to_pil()
    res, _ = _ocr(np.array(img))
    out = []
    for pts, text, conf in res or []:
        v = parse_number(text)
        if v is None:
            continue
        xs = [p[0] / scale + x0 for p in pts]
        ys = [p[1] / scale + y0 for p in pts]
        out.append(ChartValue(page, text.strip(), v, (min(xs), min(ys), max(xs), max(ys)), float(conf)))
    return out


_ocr = None


def extract_chart_values(path: Path, page: int) -> list[ChartValue]:
    vals = []
    for box in chart_regions(path, page):
        vals.extend(read_region(path, page, box))
    return vals
