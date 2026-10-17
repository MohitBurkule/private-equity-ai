import json

from fastapi.testclient import TestClient

from app.acl import format_wall
from app.main import SessionLocal, app, llm_dependency
from app.models import Deal
from app.rls import bind_tenant
from tests.test_ethical_walls_api import setup

c = TestClient(app)


def _docs(h):
    body = c.get("/documents", headers=h).json()
    return body["items"] if isinstance(body, dict) else body


class CitesEverything:
    """A fake model that cites a given document's page with a quote that is on that page."""

    def __init__(self, doc_id, quote):
        self.doc_id, self.quote = doc_id, quote

    def complete(self, system, prompt):
        return json.dumps({"claims": [{"text": "revenue is in the file", "doc_id": self.doc_id, "page": 1,
                                       "quote": self.quote}]})


def _wall(tid, grants):
    with SessionLocal() as db:
        bind_tenant(db, tid)
        db.query(Deal).filter_by(tenant_id=tid, name="Atlas").one().wall = format_wall(grants)
        db.commit()


def test_a_walled_person_does_not_see_the_walled_deals_documents_or_pages():
    admin, walled, partner, tid = setup("enforce-docs")
    _wall(tid, ["alice@fund.example"])
    atlas = next(d for d in _docs(admin) if d["deal"] == "Atlas")
    beta = next(d for d in _docs(admin) if d["deal"] == "Beta")
    walled_ids = {d["id"] for d in _docs(walled)}
    assert atlas["id"] not in walled_ids and beta["id"] in walled_ids
    assert c.get(f"/documents/{atlas['id']}/pages/1", headers=walled).status_code == 404
    assert c.get(f"/documents/{atlas['id']}/pages/1", headers=partner).status_code == 200


def test_ask_never_cites_a_document_the_walled_person_cannot_see():
    admin, walled, partner, tid = setup("enforce-ask")
    _wall(tid, ["alice@fund.example"])
    atlas_id = next(d for d in _docs(admin) if d["deal"] == "Atlas")["id"]
    app.dependency_overrides[llm_dependency] = lambda: CitesEverything(atlas_id, "enforce-ask atlas revenue")
    try:
        walled_answer = c.post("/ask", json={"question": "atlas revenue"}, headers=walled).json()
        outsider_answer = c.post("/ask", json={"question": "atlas revenue"}, headers=partner).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert all(cl["document_id"] != atlas_id for cl in walled_answer["claims"])
    assert walled_answer["claims"] == []  # the cited page is out of the walled person's scope
    assert outsider_answer["claims"], outsider_answer["rejected"][0]["reason"]
    assert outsider_answer["claims"][0]["document_id"] == atlas_id


def test_the_wall_lifts_when_the_admin_removes_it():
    admin, walled, _partner, tid = setup("enforce-lift")
    _wall(tid, ["alice@fund.example"])
    _wall(tid, [])
    atlas_id = next(d for d in _docs(admin) if d["deal"] == "Atlas")["id"]
    assert atlas_id in {d["id"] for d in _docs(walled)}
