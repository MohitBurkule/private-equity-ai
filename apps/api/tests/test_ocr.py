import io
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.facts import add_verified_fact
from app.memo import build_memo
from app.models import Document, PageRow
from app.parse import ocr
from app.parse.pdf import extract_pages

SCAN = Path("/mnt/project-files/data/uk/ch_15296432_doc1.pdf")


def test_group_lines_orders_by_row_then_x():
    def box(x, y, t, c=0.9):
        return ([[x, y], [x + 50, y], [x + 50, y + 10], [x, y + 10]], t, c)
    text, conf = ocr.group_lines([box(100, 52, "150"), box(0, 50, "Net income"), box(0, 100, "Total", 0.7)])
    assert text == "Net income  150\nTotal" and round(conf, 2) == 0.83


def test_blank_page_without_ocr_stays_empty_text_method():
    w = PdfWriter()
    w.add_blank_page(100, 100)
    b = io.BytesIO()
    w.write(b)
    p = Path("/tmp/_blank_ocr_test.pdf")
    p.write_bytes(b.getvalue())
    pages = extract_pages(p, ocr=False)
    assert pages[0].method == "text" and pages[0].text.strip() == ""


@pytest.mark.skipif(not (SCAN.exists() and ocr.available()), reason="needs scan sample and OCR extra")
def test_scanned_pdf_gets_ocr_text_marked_as_ocr():
    (page,) = extract_pages(SCAN, ocr=True)
    assert page.method == "ocr" and 0.5 < page.confidence <= 1
    assert "BRAMAND" in page.text.upper()


def test_facts_from_ocr_pages_are_not_verified_and_stay_out_of_memos():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    with Session(e) as s:
        d = Document(id="d" * 64, tenant_id="t", sha256="x", filename="scan.pdf", n_pages=1)
        d.pages = [PageRow(number=1, text="Net income 150", method="ocr", ocr_confidence=0.8)]
        s.add(d)
        s.commit()
        f = add_verified_fact(s, tenant_id="t", entity="E", metric="net_income", period="FY",
                              value=Decimal(150), unit="USD", document_id=d.id, page=1,
                              quote="Net income 150")
        assert f.status == "ocr_unverified"
        assert "Nothing to report" in build_memo(s, "t", "E")
