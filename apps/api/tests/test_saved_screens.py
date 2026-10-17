from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _seed(h):
    c.post("/targets", headers=h, json=[
        {"name": "Alpha Co", "source": "manual", "source_ref": "a", "sector": "Software", "revenue": "120",
         "revenue_url": "https://example.test/a", "country": "UK"},
        {"name": "Beta Co", "source": "manual", "source_ref": "b", "sector": "Software", "revenue": "900",
         "revenue_url": "https://example.test/b", "country": "UK"},
        {"name": "Gamma Co", "source": "manual", "source_ref": "g", "sector": "Food"},
    ])


def test_save_list_and_rerun_applies_the_same_criteria():
    h = new_tenant(c, "screens")
    _seed(h)
    saved = c.post("/targets/screens", headers=h, json={"name": "UK software 100-500", "sectors": ["Software"],
                                                       "min_revenue": "100", "max_revenue": "500"})
    assert saved.status_code == 201
    listed = c.get("/targets/screens", headers=h).json()["items"]
    assert [s["name"] for s in listed] == ["UK software 100-500"]
    sid = listed[0]["id"]
    run = c.post(f"/targets/screens/{sid}/run", headers=h).json()
    assert run["screen"] == "UK software 100-500"
    names = [i["name"] for i in run["items"]]
    assert "Alpha Co" in names and "Beta Co" not in names and "Gamma Co" not in names


def test_scores_count_passing_criteria_and_rank_them():
    h = new_tenant(c, "screens-score")
    _seed(h)
    body = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "countries": ["UK"]}).json()
    scores = {i["name"]: i["score"] for i in body["items"]}
    assert scores["Alpha Co"] == 1.0 and scores["Beta Co"] == 1.0


def test_empty_screen_is_refused_and_missing_screen_is_404():
    h = new_tenant(c, "screens-empty")
    assert c.post("/targets/screens", headers=h, json={"name": "Nothing"}).status_code == 422
    assert c.post("/targets/screens/999/run", headers=h).status_code == 404
