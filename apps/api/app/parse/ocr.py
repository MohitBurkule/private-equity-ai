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


# A page with fewer words than this, read as printed, is tried again turned. Scanned landscape pages and
# sideways tables come back as near-nothing or as junk; the right turn gives real words.
MIN_WORDS_UPRIGHT = 15
TURNS = (90, 270, 180)


def word_count(text: str) -> int:
    return sum(1 for w in text.split() if any(ch.isalnum() for ch in w))


def pick_turn(results: dict[int, tuple[str, float]]) -> int:
    """Given OCR text per turn in degrees, the turn with the most words. Ties keep the earlier turn, so an upright
    page wins over a turn that reads the same."""
    return max(results, key=lambda t: (word_count(results[t][0]), -list(results).index(t)))


def ocr_page(path: Path, index0: int, scale: float = 2.0, turn: int = 0) -> tuple[str, float]:
    global _engine
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    if _engine is None:
        _engine = RapidOCR()
    img = pdfium.PdfDocument(str(path))[index0].render(scale=scale).to_pil()
    if turn:
        img = img.rotate(turn, expand=True)
    res, _ = _engine(np.array(img))
    return group_lines(res or [])


def ocr_page_oriented(path: Path, index0: int) -> tuple[str, float, int]:
    """OCR one page, trying the other three turns only when the upright read is nearly empty. Returns the text,
    its confidence and the turn that was used, so the caller can record it."""
    text, conf = ocr_page(path, index0)
    if word_count(text) >= MIN_WORDS_UPRIGHT:
        return text, conf, 0
    results = {0: (text, conf)}
    for t in TURNS:
        results[t] = ocr_page(path, index0, turn=t)
    best = pick_turn(results)
    return results[best][0], results[best][1], best
