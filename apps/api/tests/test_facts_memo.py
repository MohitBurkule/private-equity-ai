from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.facts import CitationError, add_verified_fact
from app.memo import build_memo
from app.models import Document, PageRow

PAGE = "Statement (in millions)\nTotal revenues 1,000\nNet income 150\n"


def setup_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    d = Document(id="d" * 64, filename="acme.pdf", n_pages=1)
    d.pages = [PageRow(number=1, text=PAGE)]
    s.add(d)
    s.commit()
    return s, d.id


def test_fact_requires_matching_quote_and_number():
    s, doc = setup_db()
    kw = {"entity": "Acme", "period": "FY24", "unit": "USD", "document_id": doc, "page": 1}
    add_verified_fact(s, metric="revenue", value=Decimal(1000), quote="Total revenues 1,000", **kw)
    with pytest.raises(CitationError):
        add_verified_fact(s, metric="revenue", value=Decimal(999), quote="Total revenues 1,000", **kw)
    with pytest.raises(CitationError):
        add_verified_fact(s, metric="revenue", value=Decimal(1000), quote="Total sales 1,000", **kw)
    with pytest.raises(CitationError):
        add_verified_fact(s, metric="revenue", value=Decimal(1000), quote="x", **{**kw, "page": 2})


def test_memo_has_footnotes_and_code_derived_margin():
    s, doc = setup_db()
    kw = {"entity": "Acme", "period": "FY24", "unit": "USD", "document_id": doc, "page": 1}
    add_verified_fact(s, metric="revenue", value=Decimal(1000), quote="Total revenues 1,000", **kw)
    add_verified_fact(s, metric="net_income", value=Decimal(150), quote="Net income 150", **kw)
    md = build_memo(s, "Acme")
    assert "[1]" in md and "acme.pdf, p.1" in md
    assert "net margin (FY24): 15.00%" in md


def test_memo_empty_reports_nothing():
    s, _ = setup_db()
    assert "Nothing to report" in build_memo(s, "Nobody")


def test_api_roundtrip():
    from app.main import app
    from tests.test_ingest import blank_pdf
    c = TestClient(app)
    doc = c.post("/documents", files={"file": ("a.pdf", blank_pdf(1), "application/pdf")}).json()
    r = c.post("/facts", json={"entity": "X", "metric": "revenue", "period": "FY", "value": "1",
                               "unit": "USD", "document_id": doc["id"], "page": 1, "quote": "nope"})
    assert r.status_code == 422
    assert c.get("/memo", params={"entity": "X"}).status_code == 200
    assert c.get("/search", params={"q": "revenue"}).status_code == 200
