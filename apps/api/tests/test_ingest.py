import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.main import app
from app.models import Fact, FactSource
from tests.helpers import new_tenant


def blank_pdf(n=2) -> bytes:
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(200, 200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def test_upload_idempotent_and_page_lookup():
    c = TestClient(app)
    h = new_tenant(c, "ingest-t")
    data = blank_pdf(3)
    r1 = c.post("/documents", files={"file": ("a.pdf", data, "application/pdf")}, headers=h)
    r2 = c.post("/documents", files={"file": ("b.pdf", data, "application/pdf")}, headers=h)
    assert r1.status_code == 200 and r1.json()["n_pages"] == 3
    assert r1.json()["id"] == r2.json()["id"]
    assert c.get(f"/documents/{r1.json()['id']}/pages/3", headers=h).status_code == 200
    assert c.get(f"/documents/{r1.json()['id']}/pages/4", headers=h).status_code == 404


def test_corrupt_pdf_rejected():
    c = TestClient(app)
    r = c.post("/documents", files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
               headers=new_tenant(c, "bad-file-t"))
    assert r.status_code == 422


def test_fact_source_requires_citation_fields():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        f = Fact(tenant_id="t", entity="3M", metric="capex", period="FY2018", value=1577, unit="USD_m")
        s.add(f)
        s.flush()
        s.add(FactSource(fact_id=f.id, document_id=None, page=60, quote="x"))
        with pytest.raises(IntegrityError):
            s.flush()
