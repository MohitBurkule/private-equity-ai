from fastapi.testclient import TestClient

from app import legal
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_library_lists_every_term_and_playbook_rule_with_its_document_types():
    h = new_tenant(c, "clause-lib")
    body = c.get("/legal/clause-library", headers=h).json()
    names = {t["term"] for t in body["terms"]}
    assert names == set(legal.TERMS)
    assert len(body["playbook"]) == len(legal.PLAYBOOK)
    gov = next(t for t in body["terms"] if t["term"] == "governing_law")
    assert set(gov["documents"]) >= {"nda", "spa"}
    assert all({"id", "check", "severity", "text"} <= set(r) for r in body["playbook"])


def test_library_needs_a_key():
    assert c.get("/legal/clause-library").status_code == 401
