from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    return t["tenant_id"], {"Authorization": f"Bearer {t['api_key']}"}


def test_directory_search_matches_name_org_title_and_expertise():
    _, h = tenant("people")
    assert c.post("/people", headers=h, json={"name": "Dana Reyes", "organisation": "Acme Logistics",
                                              "title": "CFO", "expertise": ["freight", "3PL pricing"]}).status_code == 201
    assert c.post("/people", headers=h, json={"name": "Sam Ortiz", "expertise": ["cold chain"]}).status_code == 201
    assert [p["name"] for p in c.get("/people", params={"q": "freight"}, headers=h).json()["people"]] == ["Dana Reyes"]
    assert [p["name"] for p in c.get("/people", params={"q": "ACME"}, headers=h).json()["people"]] == ["Dana Reyes"]
    assert len(c.get("/people", headers=h).json()["people"]) == 2


def test_expert_sourced_for_a_walled_deal_is_hidden_from_keys_that_cannot_see_it():
    tid, owner = tenant("people-wall")
    assert c.post("/deals", headers=owner, json={"name": "Secret", "stage": "ic", "mnpi": True}).status_code == 201
    assert c.post("/people", headers=owner, json={"name": "Hidden Expert", "expertise": ["X"],
                                                  "deal": "Secret"}).status_code == 201
    assert c.post("/people", headers=owner, json={"name": "Open Expert", "expertise": ["X"]}).status_code == 201
    r = c.post(f"/admin/tenants/{tid}/keys", json={"role": "analyst", "deals": []}, headers=ADMIN).json()
    scoped = {"Authorization": f"Bearer {r['api_key']}"}
    names = [p["name"] for p in c.get("/people", params={"q": "X"}, headers=scoped).json()["people"]]
    assert names == ["Open Expert"]
    assert c.get("/people", params={"deal": "Secret"}, headers=scoped).status_code == 404
