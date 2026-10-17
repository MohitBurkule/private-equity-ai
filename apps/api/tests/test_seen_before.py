from fastapi.testclient import TestClient

from app.main import app
from app.seen_before import normalise
from tests.helpers import new_tenant

c = TestClient(app)


def test_normalise_drops_suffixes_and_punctuation():
    assert normalise("Acme Holdings, Inc.") == normalise("ACME  holdings")
    assert normalise("Widget plc") == "widget"


def test_seen_before_matches_across_records_and_respects_walls():
    h = new_tenant(c, "sb1")
    c.post("/targets", headers=h, json=[{"name": "Acme Holdings, Inc.", "source_ref": "a"}])
    c.post("/portfolio/companies", headers=h, json={"name": "Acme Labs Ltd"})
    c.post("/deals", headers=h, json={"name": "Project Acme Deal"})
    out = c.get("/seen-before?q=ACME HOLDINGS INC", headers=h).json()
    assert out["seen"] and out["hits"][0]["rule"] == "exact" and out["hits"][0]["kind"] == "target"
    out = c.get("/seen-before?q=acme", headers=h).json()
    assert [x["kind"] for x in out["hits"]] == ["target"]  # "Acme" normalises to "acme": exact, reviewer decides
    out = c.get("/seen-before?q=acme labs", headers=h).json()
    assert [x["kind"] for x in out["hits"]] == ["portfolio_company"]
    assert c.get("/seen-before?q=x", headers=h).status_code == 422
    assert c.get("/seen-before?q=Nobody Corp", headers=h).json()["seen"] is False
