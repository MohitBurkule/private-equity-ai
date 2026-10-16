"""Uniform adapters over PDF engines: every engine yields page lines with a bbox in PDF points
(origin top-left, y down) so the router and cross-checker can cite page + bbox whatever ran.

Engines import lazily; `available()` says which are installed. Licences: pypdf BSD, pdfplumber MIT,
pdfium Apache/BSD, rapidocr Apache, poppler GPL (CLI only), PyMuPDF AGPL (project is AGPL-3.0).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass(frozen=True)
class Line:
    text: str
    bbox: BBox | None
    engine: str
    conf: float | None = None


@dataclass
class PageResult:
    engine: str
    page: int  # 1-based
    lines: list[Line] = field(default_factory=list)
    method: str = "text"  # text | ocr

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


def group_words(words: list[tuple[float, float, float, float, str]], engine: str) -> list[Line]:
    """Words (x0,y0,x1,y1,text) -> lines by vertical overlap, left to right."""
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[list[tuple]] = []
    for w in words:
        mid, h = (w[1] + w[3]) / 2, max(w[3] - w[1], 1.0)
        if rows:
            r0 = rows[-1][0]
            if abs(mid - (r0[1] + r0[3]) / 2) <= max(h, r0[3] - r0[1]) * 0.5:
                rows[-1].append(w)
                continue
        rows.append([w])
    out = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        out.append(Line(" ".join(w[4] for w in r),
                        (min(w[0] for w in r), min(w[1] for w in r), max(w[2] for w in r), max(w[3] for w in r)),
                        engine))
    return out


def _pymupdf(path, pages):
    import pymupdf
    doc = pymupdf.open(str(path))
    for p in pages:
        words = [(w[0], w[1], w[2], w[3], w[4]) for w in doc[p - 1].get_text("words")]
        yield PageResult("pymupdf", p, group_words(words, "pymupdf"))


def _pymupdf_layout_text(path, pages):
    """PyMuPDF block text sorted; used where its word grouping splits rows."""
    import pymupdf
    doc = pymupdf.open(str(path))
    for p in pages:
        yield PageResult("pymupdf_text", p, [Line(t, None, "pymupdf_text") for t in doc[p - 1].get_text("text", sort=True).splitlines() if t.strip()])


def _pdfplumber(path, pages):
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        for p in pages:
            ws = pdf.pages[p - 1].extract_words(keep_blank_chars=False, use_text_flow=False)
            yield PageResult("pdfplumber", p, group_words([(w["x0"], w["top"], w["x1"], w["bottom"], w["text"]) for w in ws], "pdfplumber"))


def _pypdf(path, pages):
    from pypdf import PdfReader
    r = PdfReader(str(path))
    for p in pages:
        try:
            t = r.pages[p - 1].extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001
            t = ""
        yield PageResult("pypdf", p, [Line(x, None, "pypdf") for x in t.splitlines() if x.strip()])


def _pdftotext(path, pages):
    """poppler `-bbox-layout`: lines with coordinates, reading order from poppler's layout analysis."""
    for p in pages:
        out = subprocess.run(["pdftotext", "-bbox-layout", "-f", str(p), "-l", str(p), str(path), "-"],
                             capture_output=True, text=True, check=False).stdout
        lines = []
        for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', out, re.DOTALL):
            ws = re.findall(r"<word[^>]*>(.*?)</word>", m.group(5), re.DOTALL)
            txt = " ".join(ws).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
            lines.append(Line(txt, tuple(float(m.group(i)) for i in range(1, 5)), "pdftotext"))
        yield PageResult("pdftotext", p, lines)


def _pdftotext_layout(path, pages):
    """poppler -layout: columns padded with spaces, so table rows stay on one line."""
    for p in pages:
        out = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), str(path), "-"],
                             capture_output=True, text=True, check=False).stdout
        yield PageResult("pdftotext_layout", p, [Line(x.strip(), None, "pdftotext_layout") for x in out.splitlines() if x.strip()])


def _pdfium(path, pages):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    for p in pages:
        tp = doc[p - 1].get_textpage()
        yield PageResult("pdfium", p, [Line(x.strip(), None, "pdfium") for x in tp.get_text_range().splitlines() if x.strip()])


_ocr = None


def _rapidocr(path, pages, scale: float = 2.0):
    global _ocr
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    _ocr = _ocr or RapidOCR()
    doc = pdfium.PdfDocument(str(path))
    for p in pages:
        img = doc[p - 1].render(scale=scale).to_pil()
        res, _ = _ocr(np.array(img))
        words = []
        for pts, text, conf in res or []:
            xs, ys = [q[0] / scale for q in pts], [q[1] / scale for q in pts]
            words.append((min(xs), min(ys), max(xs), max(ys), text, float(conf)))
        lines = group_words([w[:5] for w in words], "rapidocr")
        conf = sum(w[5] for w in words) / len(words) if words else None
        yield PageResult("rapidocr", p, [Line(ln.text, ln.bbox, "rapidocr", conf) for ln in lines], method="ocr")


def _camelot(path, pages):
    """Camelot stream tables (text-layer only): one line per table row, cells joined by ' | '."""
    import camelot
    for p in pages:
        lines: list[Line] = []
        try:
            tables = camelot.read_pdf(str(path), pages=str(p), flavor="stream")
        except Exception:  # noqa: BLE001  camelot raises on pages without tables
            tables = []
        for t in tables:
            x0, y0, x1, y1 = t._bbox
            h = t.pdf_size[1] if hasattr(t, "pdf_size") else 0
            for row in t.df.itertuples(index=False):
                cells = [str(c).strip() for c in row if str(c).strip()]
                if cells:
                    lines.append(Line(" | ".join(cells), (x0, h - y1, x1, h - y0) if h else None, "camelot"))
        yield PageResult("camelot", p, lines)


_docling = None


def _docling_engine(path, pages):
    """Docling (layout model + TableFormer). Tables become one line per row, cells joined by ' | '."""
    global _docling
    from docling.document_converter import DocumentConverter
    _docling = _docling or DocumentConverter()
    for p in pages:
        doc = _docling.convert(str(path), page_range=(p, p)).document
        lines: list[Line] = []
        for item, _ in doc.iterate_items():
            prov = getattr(item, "prov", None)
            bb = None
            if prov:
                h = doc.pages[prov[0].page_no].size.height
                b = prov[0].bbox
                bb = (b.l, h - b.t, b.r, h - b.b) if b.coord_origin.name == "BOTTOMLEFT" else (b.l, b.t, b.r, b.b)
            data = getattr(item, "data", None)
            if data is not None and getattr(data, "grid", None):
                for row in data.grid:
                    cells = [c.text.strip() for c in row if c.text.strip()]
                    if cells:
                        lines.append(Line(" | ".join(dict.fromkeys(cells)), bb, "docling"))
            elif getattr(item, "text", "").strip():
                lines.append(Line(item.text.strip(), bb, "docling"))
        yield PageResult("docling", p, lines)


ENGINES = {
    "pdftotext": (_pdftotext, lambda: shutil.which("pdftotext") is not None),
    "pdftotext_layout": (_pdftotext_layout, lambda: shutil.which("pdftotext") is not None),
    "pymupdf": (_pymupdf, lambda: _has("pymupdf")),
    "pymupdf_text": (_pymupdf_layout_text, lambda: _has("pymupdf")),
    "pdfplumber": (_pdfplumber, lambda: _has("pdfplumber")),
    "pypdf": (_pypdf, lambda: _has("pypdf")),
    "pdfium": (_pdfium, lambda: _has("pypdfium2")),
    "camelot": (_camelot, lambda: _has("camelot")),
    "docling": (_docling_engine, lambda: _has("docling")),
    "rapidocr": (_rapidocr, lambda: _has("rapidocr_onnxruntime") and _has("pypdfium2")),
}


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def available() -> list[str]:
    return [n for n, (_, ok) in ENGINES.items() if ok()]


def run(engine: str, path: Path, pages: list[int]) -> list[PageResult]:
    fn, ok = ENGINES[engine]
    if not ok():
        raise RuntimeError(f"engine {engine} not installed")
    return list(fn(path, pages))
