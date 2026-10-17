from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _seed(h):
    c.post("/targets", headers=h, json=[
        {"name": "Delta Co", "source": "manual", "source_ref": "d", "sector": "Software", "country": "UK"},
    ])


def test_unweighted_score_is_share_of_tests_passing():
    h = new_tenant(c, "weights-plain")
    _seed(h)
    body = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "countries": ["UK"],
                                                      "min_revenue": "100"}).json()
    assert body["items"][0]["score"] == 0.67  # sector and country pass, revenue unknown


def test_firm_weight_on_unknown_criterion_lifts_score():
    h = new_tenant(c, "weights-set")
    _seed(h)
    body = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "countries": ["UK"],
                                                      "min_revenue": "100",
                                                      "weights": {"revenue": 0}}).json()
    assert body["items"][0]["score"] == 1.0
    assert body["applied"]["weights"] == {"revenue": 0.0}


def test_bad_weights_are_refused():
    h = new_tenant(c, "weights-bad")
    unknown = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "weights": {"size": 1}})
    assert unknown.status_code == 422
    negative = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "weights": {"sector": -1}})
    assert negative.status_code == 422


def test_saved_screen_keeps_weights_on_rerun():
    h = new_tenant(c, "weights-saved")
    _seed(h)
    c.post("/targets/screens", headers=h, json={"name": "weighted", "sectors": ["Software"],
                                               "countries": ["UK"], "min_revenue": "100",
                                               "weights": {"revenue": 0}})
    sid = c.get("/targets/screens", headers=h).json()["items"][0]["id"]
    run = c.post(f"/targets/screens/{sid}/run", headers=h).json()
    assert run["items"][0]["score"] == 1.0
