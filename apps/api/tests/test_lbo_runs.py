"""Saved LBO runs: a save goes through the same citation gate, and runs are listed only for their own tenant."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_lbo import BASE, SRC

c = TestClient(app)


def _request():
    return {"inputs": {k: {"value": v, "source": SRC} for k, v in BASE.items()}}


def test_save_list_and_reopen_a_run():
    h = new_tenant(c, "lbo-runs")
    saved = c.post("/lbo/runs", headers=h, json={"name": "Base case", "request": _request()})
    assert saved.status_code == 200 and saved.json()["moic"] == c.post("/lbo/returns", headers=h, json=_request()).json()["moic"]
    run_id = saved.json()["id"]
    listed = c.get("/lbo/runs", headers=h).json()
    assert [r["name"] for r in listed] == ["Base case"]
    got = c.get(f"/lbo/runs/{run_id}", headers=h).json()
    assert got["request"] == _request() and got["result"]["equity"] == "520"


def test_save_refuses_uncited_input_and_other_tenant_cannot_read():
    h = new_tenant(c, "lbo-runs-a")
    other = new_tenant(c, "lbo-runs-b")
    bad = {"inputs": {**_request()["inputs"], "ebitda": {"value": "100"}}}
    assert c.post("/lbo/runs", headers=h, json={"name": "x", "request": bad}).status_code == 422
    assert c.post("/lbo/runs", headers=h, json={"name": " ", "request": _request()}).status_code == 422
    run_id = c.post("/lbo/runs", headers=h, json={"name": "A", "request": _request()}).json()["id"]
    assert c.get(f"/lbo/runs/{run_id}", headers=other).status_code == 404
    assert c.get("/lbo/runs", headers=other).json() == []
