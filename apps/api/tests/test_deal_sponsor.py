from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_sponsor_is_saved_and_seen_before_matches_it():
    h = new_tenant(c, "sponsor")
    r = c.post("/deals", headers=h, json={"name": "Sponsor Deal", "sponsor": "Apex Capital Partners"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["sponsor"] == "Apex Capital Partners"
    hits = c.get("/seen-before", params={"q": "Apex Capital"}, headers=h).json()["hits"]
    assert [(x["name"], x["rule"]) for x in hits] == [("Sponsor Deal", "sponsor")]


def test_sponsor_can_be_edited_and_shows_on_snapshot():
    h = new_tenant(c, "sponsor2")
    assert c.post("/deals", headers=h, json={"name": "Edit Deal"}).status_code in (200, 201)
    assert c.get("/seen-before", params={"q": "Blue Harbor"}, headers=h).json()["seen"] is False
    r = c.patch("/deals/Edit Deal", headers=h, json={"sponsor": "Blue Harbor Equity"})
    assert r.status_code == 200, r.text
    assert c.get("/seen-before", params={"q": "Blue Harbor"}, headers=h).json()["seen"] is True
    assert c.get("/deals/Edit Deal/snapshot", headers=h).json()["sponsor"] == "Blue Harbor Equity"
    c.patch("/deals/Edit Deal", headers=h, json={"sponsor": "  "})
    assert c.get("/deals/Edit Deal/snapshot", headers=h).json()["sponsor"] is None
