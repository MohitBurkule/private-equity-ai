from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_save_list_and_rerun_under_the_rerunners_access():
    h = new_tenant(c, "saved-search")
    assert c.post("/search/saved", headers=h, json={"name": "covenant", "query": "covenant headroom"}).status_code == 201
    rows = c.get("/search/saved", headers=h).json()["items"]
    assert [r["name"] for r in rows] == ["covenant"]
    run = c.get(f"/search/saved/{rows[0]['id']}/run", headers=h).json()
    assert run["search"] == "covenant" and isinstance(run["items"], list)


def test_missing_saved_search_is_404_and_other_tenants_cannot_run_it():
    h = new_tenant(c, "saved-search-a")
    other = new_tenant(c, "saved-search-b")
    c.post("/search/saved", headers=h, json={"name": "private", "query": "net debt"})
    sid = c.get("/search/saved", headers=h).json()["items"][0]["id"]
    assert c.get(f"/search/saved/{sid}/run", headers=other).status_code == 404
    assert c.get("/search/saved/999/run", headers=h).status_code == 404
