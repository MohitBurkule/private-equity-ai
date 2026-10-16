"""Roles and deal walls on the newer endpoints: deals, holdings, DDQ, report, tie-out, sum check."""
import pytest
from fastapi.testclient import TestClient

from app.main import app, llm_dependency

ADMIN = {"X-Admin-Token": "test-admin"}
CSV = "Company,Shares,Price,Currency\nAcme,1,1,GBP\n"


@pytest.fixture()
def world():
    c = TestClient(app)
    t = c.post("/admin/tenants", json={"name": "nacl"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}

    def mint(**kw):
        r = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json=kw, headers=ADMIN)
        assert r.status_code == 201, r.text
        return {"Authorization": f"Bearer {r.json()['api_key']}"}
    return c, owner, mint


def test_viewer_is_read_only_everywhere_new(world):
    c, owner, mint = world
    viewer = mint(role="viewer")
    c.post("/deals", headers=owner, json={"name": "Atlas"})
    assert c.post("/deals", headers=viewer, json={"name": "X"}).status_code == 403
    assert c.patch("/deals/Atlas", headers=viewer, json={"stage": "ic"}).status_code == 403
    assert c.post("/holdings/import", headers=viewer, data={"platform": "p"},
                  files={"file": ("h.csv", CSV, "text/csv")}).status_code == 403
    assert [d["name"] for d in c.get("/deals", headers=viewer).json()] == ["Atlas"]
    assert c.get("/portfolio/report", headers=viewer).status_code == 200
    assert c.post("/calc/sumcheck", headers=viewer, json={"parts": ["1"], "stated": "1"}).json()["status"] == "ties"


def test_walled_key_sees_only_its_deals_and_cannot_touch_holdings(world):
    c, owner, mint = world
    c.post("/deals", headers=owner, json={"name": "alpha"})
    c.post("/deals", headers=owner, json={"name": "bravo"})
    c.post("/holdings/import", headers=owner, data={"platform": "p"}, files={"file": ("h.csv", CSV, "text/csv")})
    walled = mint(role="analyst", deals=["alpha"])
    assert [d["name"] for d in c.get("/deals", headers=walled).json()] == ["alpha"]
    assert c.patch("/deals/bravo", headers=walled, json={"stage": "ic"}).status_code == 404
    assert c.post("/deals", headers=walled, json={"name": "new"}).status_code == 403
    assert c.get("/holdings", headers=walled).json() == []
    assert c.post("/holdings/import", headers=walled, data={"platform": "p"},
                  files={"file": ("g.csv", CSV.replace("Acme", "Other"), "text/csv")}).status_code == 403
    empty = mint(role="analyst", deals=[])
    assert c.get("/deals", headers=empty).json() == []


def test_ddq_respects_wall_and_limits(world):
    c, owner, mint = world

    class Never:
        def complete(self, system, prompt):
            raise AssertionError("no page is visible, the model must not be called")
    app.dependency_overrides[llm_dependency] = lambda: Never()
    try:
        c.post("/documents", headers=owner, files={"file": ("a.csv", "k,v\nrevenue,5\n", "text/csv")},
               data={"deal": "bravo"})
        walled = mint(role="analyst", deals=["alpha"])
        r = c.post("/ddq", headers=walled, json={"questions": ["what is revenue"]})
        assert r.status_code == 200 and r.json()["items"][0]["status"] == "not_found"
        assert r.json()["needs_human"] == 1
    finally:
        app.dependency_overrides.clear()


def test_bad_inputs_are_422_not_500(world):
    c, owner, _ = world
    assert c.post("/calc/sumcheck", headers=owner, json={"parts": ["x"], "stated": "1"}).status_code == 422
    assert c.post("/calc/tieout", headers=owner, json={"rows": {"a": ["1", "2", "3"]}, "base": ["0"], "total": ["0"]}).json()["status"] == "no_solution"
    assert c.post("/calc/tieout", headers=owner, json={"rows": {}, "base": ["1"], "total": ["1", "2"]}).json()["status"] == "no_solution"
    assert c.post("/deals", headers=owner, json={"name": "a", "stage": "nope"}).status_code == 422
