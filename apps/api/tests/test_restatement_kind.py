"""A disagreement between versions of one model is a restatement; across unrelated sources it stays a conflict."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_conflicts_dd import fact, up

c = TestClient(app)


def test_versions_of_one_model_are_a_restatement_with_the_newer_one_named():
    h = new_tenant(c, "rk1")
    v3 = up(h, [("ebitda", 200)], "model_v3.xlsx")
    v5 = up(h, [("ebitda", 230)], "model_v5.xlsx")
    fact(h, v3, 200, metric="ebitda")
    fact(h, v5, 230, metric="ebitda")
    out = c.get("/facts/conflicts", headers=h).json()
    assert len(out) == 1
    assert out[0]["kind"] == "restatement"
    assert out[0]["superseded_by"] == {str(v3): str(v5)}


def test_unrelated_sources_stay_a_conflict():
    h = new_tenant(c, "rk2")
    d1 = up(h, [("ebitda", 200)], "cim.xlsx")
    d2 = up(h, [("ebitda", 230)], "qoe.xlsx")
    fact(h, d1, 200, metric="ebitda")
    fact(h, d2, 230, metric="ebitda")
    out = c.get("/facts/conflicts", headers=h).json()
    assert len(out) == 1 and out[0]["kind"] == "conflict"
