"""Cross-tenant attack tests: every read and write path must refuse another tenant's data."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.audit import log_event, verify_chain
from app.facts import CitationError, add_verified_fact
from app.main import app, engine
from tests.helpers import new_tenant
from tests.test_ingest import blank_pdf
from tests.test_xlsx import make_xlsx  # noqa: F401


@pytest.fixture
def two_tenants():
    c = TestClient(app)
    return c, new_tenant(c, "alpha"), new_tenant(c, "beta")


def upload_xlsx(c, h, text):
    wb = Workbook()
    wb.active["A1"] = text
    wb.active["B1"] = 1234
    import io
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]


def test_requests_without_valid_token_rejected(two_tenants):
    c, _, _ = two_tenants
    assert c.get("/documents").status_code == 401
    assert c.get("/documents", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/admin/tenants", json={"name": "x"}).status_code == 403
    assert c.post("/admin/tenants", json={"name": "x"}, headers={"X-Admin-Token": "bad"}).status_code == 403


def test_same_file_two_tenants_get_separate_documents(two_tenants):
    c, a, b = two_tenants
    data = blank_pdf(2)
    ida = c.post("/documents", files={"file": ("f.pdf", data, "application/pdf")}, headers=a).json()["id"]
    idb = c.post("/documents", files={"file": ("f.pdf", data, "application/pdf")}, headers=b).json()["id"]
    assert ida != idb
    assert [d["id"] for d in c.get("/documents", headers=a).json()] == [ida]


def test_cannot_read_search_or_cite_other_tenants_document(two_tenants):
    c, a, b = two_tenants
    doc = upload_xlsx(c, a, "secret deal revenue")
    assert c.get(f"/documents/{doc}/pages/1", headers=b).status_code == 404
    assert c.get("/search", params={"q": "secret deal", "doc_id": doc}, headers=b).status_code == 404
    assert c.get("/search", params={"q": "secret deal revenue"}, headers=b).json() == []
    assert c.get("/search", params={"q": "secret deal revenue"}, headers=a).json() != []
    r = c.post("/facts", headers=b, json={
        "entity": "X", "metric": "revenue", "period": "FY", "value": "1234", "unit": "USD",
        "document_id": doc, "page": 1, "quote": "Sheet!B1: 1,234"})
    assert r.status_code == 404


def test_memo_and_portfolio_are_tenant_scoped(two_tenants):
    c, a, b = two_tenants
    doc = upload_xlsx(c, a, "Revenue")
    quote = c.get(f"/documents/{doc}/pages/1", headers=a).json()["text"].splitlines()[1]
    fid = c.post("/facts", headers=a, json={
        "entity": "Acme", "metric": "revenue", "period": "FY24", "value": "1234", "unit": "USD",
        "document_id": doc, "page": 1, "quote": quote}).json()["id"]
    assert "1,234.00" in c.get("/memo", params={"entity": "Acme"}, headers=a).json()["markdown"]
    assert "Nothing to report" in c.get("/memo", params={"entity": "Acme"}, headers=b).json()["markdown"]
    cb = c.post("/portfolio/companies", json={"name": "BetaCo"}, headers=b).json()["id"]
    r = c.post(f"/portfolio/companies/{cb}/observations", params={"fact_id": fid}, headers=b)
    assert r.status_code == 422  # beta cannot attach alpha's fact
    ca = c.post("/portfolio/companies", json={"name": "AlphaCo"}, headers=a).json()["id"]
    assert c.post(f"/portfolio/companies/{ca}/observations", params={"fact_id": fid}, headers=b).status_code == 422
    assert c.post(f"/portfolio/companies/{ca}/observations", params={"fact_id": fid}, headers=a).status_code == 201
    assert c.get(f"/portfolio/companies/{ca}/kpis", headers=b).json() == []


def test_audit_chains_are_independent_per_tenant():
    from app.main import SessionLocal
    from app.rls import bind_tenant
    with SessionLocal() as s:
        bind_tenant(s, "chain-a")
        log_event(s, "chain-a", "u", "x", {"i": 1})
        bind_tenant(s, "chain-b")
        log_event(s, "chain-b", "u", "x", {"i": 1})
        bind_tenant(s, "chain-a")
        log_event(s, "chain-a", "u", "x", {"i": 2})
        assert verify_chain(s, "chain-a") == (True, None)
        bind_tenant(s, "chain-b")
        assert verify_chain(s, "chain-b") == (True, None)


def test_add_verified_fact_rejects_other_tenants_doc():
    c = TestClient(app)
    doc = upload_xlsx(c, new_tenant(c, "owner"), "Revenue")
    from app.rls import bind_tenant
    with Session(engine) as s, pytest.raises(CitationError):
        bind_tenant(s, "intruder")
        add_verified_fact(s, tenant_id="intruder", entity="E", metric="m", period="p",
                          value=Decimal(1234), unit="USD", document_id=doc, page=1,
                          quote="Sheet!B1: 1,234")
