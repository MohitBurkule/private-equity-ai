from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_deal_lifecycle_and_summary():
    h = new_tenant(c, "dl1")
    r = c.post("/deals", headers=h, json={"name": "Project Atlas"})
    assert r.status_code == 201 and r.json()["stage"] == "sourcing"
    assert c.post("/deals", headers=h, json={"name": "Project Atlas"}).status_code == 409
    assert c.post("/deals", headers=h, json={"name": "X", "stage": "bogus"}).status_code == 422
    assert c.post("/deals", headers=h, json={"name": "  "}).status_code == 422
    c.post("/dd/requests/seed", headers=h, json={"deal": "Project Atlas", "categories": ["legal"]})
    r = c.patch("/deals/Project Atlas", headers=h, json={"stage": "dd", "note": "kickoff"})
    assert r.json()["stage"] == "dd" and r.json()["dd_open"] == r.json()["dd_total"] > 0
    assert [d["name"] for d in c.get("/deals", headers=h).json()] == ["Project Atlas"]
    assert c.patch("/deals/nope", headers=h, json={"stage": "ic"}).status_code == 404


def test_deals_tenant_isolated():
    a, b = new_tenant(c, "dl2"), new_tenant(c, "dl3")
    c.post("/deals", headers=a, json={"name": "Secret"})
    assert c.get("/deals", headers=b).json() == []
    assert c.patch("/deals/Secret", headers=b, json={"stage": "ic"}).status_code == 404
