from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.citations import locator_label, xlsx_location
from app.db import Base, make_engine
from app.facts import CitationError, add_verified_fact
from app.ingest import ingest_xlsx
from app.memo import build_memo
from app.parse.xlsx import iter_sheet_chunks


def _book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws.append(["Revenue", 1234])
    ws.append(["Cost of sales", 900])
    for i in range(200):
        ws.append([f"line {i}", i * 7])
    empty = wb.create_sheet("Notes")
    empty.sheet_state = "hidden"
    wb.save(path)
    return path


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_chunks_are_bounded_numbered_and_keep_every_line(tmp_path):
    p = _book(tmp_path / "a.xlsx")
    chunks = list(iter_sheet_chunks(p, chunk_chars=500))
    assert [c.number for c in chunks] == list(range(1, len(chunks) + 1))
    assert len(chunks) > 3
    assert all(c.name == "P&L" for c in chunks[:-1]) and chunks[-1].name in ("P&L", "Notes")
    assert all(len(c.text) < 500 + 200 for c in chunks)  # a chunk ends at a row, so it overshoots by one row
    joined = "\n".join(c.text for c in chunks)
    assert "P&L!B2: 900 | row: Cost of sales" in joined and "P&L!A202: line 199" in joined


def test_ingest_stores_each_chunk_as_a_page_labelled_with_its_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr("app.parse.xlsx.CHUNK_CHARS", 500)
    s = _session()
    doc = ingest_xlsx(s, "t", _book(tmp_path / "a.xlsx"), "a.xlsx")
    assert doc.kind == "xlsx" and doc.n_pages == len(doc.pages) > 3
    assert {p.label for p in doc.pages} == {"P&L", "Notes"}


def test_workbook_fact_cites_sheet_cell_and_row_never_a_page(tmp_path):
    s = _session()
    doc = ingest_xlsx(s, "t", _book(tmp_path / "a.xlsx"), "a.xlsx")
    first = doc.pages[0]
    add_verified_fact(s, tenant_id="t", entity="Acme", metric="revenue", period="FY24", value=Decimal(1234),
                      unit="USD", document_id=doc.id, page=first.number, quote="P&L!B1: 1,234 | row: Revenue")
    fact = s.query(__import__("app.models", fromlist=["Fact"]).Fact).one()
    src = fact.sources[0]
    assert (src.kind, src.heading, src.anchor, src.section) == ("xlsx", "P&L", "B1", "Revenue")
    assert src.locator == "P&L!B1, row: Revenue"
    memo = build_memo(s, "t", "Acme")
    assert "P&L!B1, row: Revenue" in memo and "p." not in memo.split("Sources")[0].split("[1]")[-1]


def test_workbook_quote_must_name_its_cell_and_the_cited_sheet(tmp_path):
    s = _session()
    doc = ingest_xlsx(s, "t", _book(tmp_path / "a.xlsx"), "a.xlsx")
    kw = {"tenant_id": "t", "entity": "Acme", "metric": "revenue", "period": "FY24", "value": Decimal(1234),
          "unit": "USD", "document_id": doc.id, "page": doc.pages[0].number}
    with pytest.raises(CitationError):
        add_verified_fact(s, quote="Revenue 1,234", **kw)  # no cell address
    with pytest.raises(CitationError):
        add_verified_fact(s, quote="Other!B1: 1,234", **kw)  # names a sheet this page is not


def test_locator_labels_by_kind():
    assert locator_label(3) == "p.3"
    assert locator_label(0, kind="xlsx", heading="P&L", anchor="C14", section="Revenue") == "P&L!C14, row: Revenue"
    assert locator_label(0, kind="xlsx", heading="P&L", anchor="C14") == "P&L!C14"
    assert locator_label(0, "7.12", "Financial Covenants", kind="html") == "§7.12 Financial Covenants"
    assert xlsx_location("P&L!C14: 1,000 | row: Revenue") == ("P&L", "C14", "Revenue")
    assert xlsx_location("no cell here") is None
