"""Find the figures on each page of a PDF and keep where they sit, so a chart value can later cite its figure.

Slice one finds raster images only. Each one is stored with its page and a top-left bbox in PDF points. Nothing
here reads a value off a figure: chart numbers only become facts through the review queue, as ocr_unverified.
Vector charts (drawn with paths, not embedded pictures) are not found yet; that is a later slice.

Bboxes are in the page's unrotated coordinates, the same space the page image is rendered in for a citation,
so a rotated page can have its figures placed a quarter turn off until rotation is handled.
"""
from __future__ import annotations

from dataclasses import dataclass

import pypdfium2 as pdfium
from pypdfium2 import raw
from sqlalchemy.orm import Session

from app.models import PageFigure

MIN_SIDE_PT = 40  # rules, bullets and logos are smaller than any chart worth citing


@dataclass(frozen=True)
class Figure:
    page: int
    kind: str  # "image"
    bbox: tuple[float, float, float, float]  # left, top, right, bottom in PDF points, top-left origin


def detect_figures(pdf: bytes) -> list[Figure]:
    out: list[Figure] = []
    doc = pdfium.PdfDocument(pdf)
    try:
        for index in range(len(doc)):
            page = doc[index]
            width, height = page.get_width(), page.get_height()
            try:
                for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
                    left, bottom, right, top = obj.get_bounds()
                    if right - left < MIN_SIDE_PT or top - bottom < MIN_SIDE_PT:
                        continue
                    box = (max(0.0, left), max(0.0, height - top), min(width, right), min(height, height - bottom))
                    out.append(Figure(page=index + 1, kind="image", bbox=box))
            finally:
                page.close()
    finally:
        doc.close()
    return out


def store_figures(db: Session, tenant_id: str, document_id: str, figures: list[Figure]) -> int:
    """Replace the document's figures with this detection. Re-running detection is safe; old rows never linger."""
    db.query(PageFigure).filter_by(tenant_id=tenant_id, document_id=document_id).delete()
    for f in figures:
        left, top, right, bottom = f.bbox
        db.add(PageFigure(tenant_id=tenant_id, document_id=document_id, page=f.page, kind=f.kind,
                          left=left, top=top, right=right, bottom=bottom))
    return len(figures)
