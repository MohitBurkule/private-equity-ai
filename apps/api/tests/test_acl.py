import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.llm import LLM
from app.main import app, llm_dependency

ADMIN = {"X-Admin-Token": "test-admin"}


def xlsx(text):
    wb = Workbook()
    wb.active["A1"] = text
    wb.active["B1"] = 1234
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def up(c, h, text, deal=None):
    return c.post("/documents", files={"file": ("m.xlsx", xlsx(text), "x")},
                  data={"deal": deal} if deal else {}, headers=h)


@pytest.fixture()
def world():
    c = TestClient(app)
    tenants = c.post("/admin/tenants", json={"name": "acl2"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {tenants['api_key']}"}

    def mint(**kw):
        r = c.post(f"/admin/tenants/{tenants['tenant_id']}/keys", json=kw, headers=ADMIN)
        assert r.status_code == 201, r.text
        return {"Authorization": f"Bearer {r.json()['api_key']}"}
    return c, owner, mint


def test_wall_hides_documents_search_pages_memo_and_facts(world):
    c, owner, mint = world
    a = up(c, owner, "alpha deal revenue", "alpha").json()["id"]
    b = up(c, owner, "bravo deal revenue", "bravo").json()["id"]
    untagged = up(c, owner, "untagged revenue").json()["id"]
    for doc, ent in ((a, "A"), (b, "B")):
        assert c.post("/facts", headers=owner, json={
            "entity": ent, "metric": "revenue", "period": "FY", "value": "1234", "unit": "USD",
            "document_id": doc, "page": 1, "quote": "Sheet!B1: 1,234"}).status_code == 201
    walled = mint(role="analyst", deals=["alpha"])
    ids = {d["id"] for d in c.get("/documents", headers=walled).json()}
    assert ids == {a}
    assert {d["id"] for d in c.get("/documents", headers=owner).json()} == {a, b, untagged}
    assert c.get(f"/documents/{b}/pages/1", headers=walled).status_code == 404
    assert c.get(f"/documents/{untagged}/pages/1", headers=walled).status_code == 404
    assert c.get(f"/documents/{a}/pages/1", headers=walled).status_code == 200
    hits = c.get("/search", params={"q": "deal revenue"}, headers=walled).json()
    assert {h["document_id"] for h in hits} == {a}
    assert c.get("/search", params={"q": "x", "doc_id": b}, headers=walled).status_code == 404
    assert "1,234" in c.get("/memo", params={"entity": "A"}, headers=walled).json()["markdown"]
    assert "No verified facts" in c.get("/memo", params={"entity": "B"}, headers=walled).json()["markdown"]
    assert c.get("/memo.docx", params={"entity": "B"}, headers=walled).status_code == 200
    # cannot create a fact on a walled document
    r = c.post("/facts", headers=walled, json={
        "entity": "B", "metric": "revenue", "period": "FY", "value": "1234", "unit": "USD",
        "document_id": b, "page": 1, "quote": "Sheet!B1: 1,234"})
    assert r.status_code == 404


def test_walled_upload_needs_in_scope_deal_and_viewer_is_read_only(world):
    c, _owner, mint = world
    walled = mint(deals=["alpha"])
    assert up(c, walled, "no deal tag").status_code == 403
    assert up(c, walled, "wrong deal", "bravo").status_code == 403
    r = up(c, walled, "right deal", "alpha")
    assert r.status_code == 200 and r.json()["deal"] == "alpha"
    viewer = mint(role="viewer")
    assert up(c, viewer, "x").status_code == 403
    assert c.post("/portfolio/companies", json={"name": "Co"}, headers=viewer).status_code == 403
    assert c.get("/documents", headers=viewer).status_code == 200
    assert c.post("/admin/tenants/x/keys", json={"role": "boss"}, headers=ADMIN).status_code in (404, 422)


def test_empty_scope_sees_nothing_and_bad_role_rejected(world):
    c, owner, mint = world
    tid = c.post("/admin/tenants", json={"name": "t3"}, headers=ADMIN).json()["tenant_id"]
    assert c.post(f"/admin/tenants/{tid}/keys", json={"role": "boss"}, headers=ADMIN).status_code == 422
    up(c, owner, "something", "alpha")
    nothing = mint(deals=[])
    assert c.get("/documents", headers=nothing).json() == []
    assert c.get("/search", params={"q": "something"}, headers=nothing).json() == []


def test_duplicate_content_across_walls_is_not_exposed_or_merged(world):
    c, owner, mint = world
    up(c, owner, "same bytes", "bravo")
    walled = mint(deals=["alpha"])
    assert up(c, walled, "same bytes", "alpha").status_code == 409


class Cheater(LLM):
    """Model that tries to cite a walled document by id."""
    def __init__(self, doc, quote):
        self.doc, self.quote = doc, quote

    def complete(self, system, user):
        return ('{"claims":[{"text":"Revenue is 1,234","doc_id":"' + self.doc
                + '","page":1,"quote":"' + self.quote + '"}]}')


def test_model_cannot_cite_walled_document(world):
    c, owner, mint = world
    b = up(c, owner, "bravo secret revenue", "bravo").json()["id"]
    up(c, owner, "alpha plain revenue", "alpha")
    walled = mint(deals=["alpha"])
    app.dependency_overrides[llm_dependency] = lambda: Cheater(b, "Sheet!B1: 1,234")
    try:
        r = c.post("/ask", json={"question": "revenue"}, headers=walled).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert r["status"] == "not_found" and r["claims"] == []
    assert r["rejected"] and r["rejected"][0]["reason"] == "cited page not found"
