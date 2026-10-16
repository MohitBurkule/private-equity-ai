"""OCR fallback for pages without a text layer (rapidocr-onnxruntime + pypdfium2, both permissive).

Install the extra: pip install '.[ocr]'. OCR text is never treated as verified: facts quoted from
an OCR page get status `ocr_unverified` and stay out of memos until a person confirms them.
"""
from __future__ import annotations

from pathlib import Path

_engine = None


def available() -> bool:
    try:
        import pypdfium2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def group_lines(boxes: list[tuple[list[list[float]], str, float]]) -> tuple[str, float]:
    """Cluster OCR boxes into text lines by vertical centre; returns (text, mean confidence)."""
    items = []
    for pts, text, conf in boxes:
        ys = [p[1] for p in pts]
        xs = [p[0] for p in pts]
        items.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), text, float(conf)))
    items.sort(key=lambda t: (t[0], t[2]))
    lines: list[list[tuple]] = []
    for it in items:
        if lines and abs(it[0] - lines[-1][0][0]) <= max(it[1], lines[-1][0][1]) * 0.5:
            lines[-1].append(it)
        else:
            lines.append([it])
    text = "\n".join("  ".join(t[3] for t in sorted(line, key=lambda t: t[2])) for line in lines)
    conf = sum(i[4] for i in items) / len(items) if items else 0.0
    return text, conf


def ocr_page(path: Path, index0: int, scale: float = 2.0) -> tuple[str, float]:
    global _engine
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    if _engine is None:
        _engine = RapidOCR()
    img = pdfium.PdfDocument(str(path))[index0].render(scale=scale).to_pil()
    res, _ = _engine(np.array(img))
    return group_lines(res or [])
