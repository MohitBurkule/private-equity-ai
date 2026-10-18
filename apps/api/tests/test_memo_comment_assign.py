"""Memo comments: assign to someone, resolve, reopen. Whole-tenant keys only, like the rest of memo versions."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _version(h):
    r = c.post("/memo/versions?entity=Acme", headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_comment_assign_resolve_and_reopen():
    h = new_tenant(c, "mca1")
    v = _version(h)
    cid = c.post(f"/memo/versions/{v}/comments", headers=h,
                 json={"body": "Check the FY23 margin", "assignee": "priya"}).json()["id"]
    got = c.get(f"/memo/versions/{v}", headers=h).json()["comments"][0]
    assert got["assignee"] == "priya" and got["status"] == "open"

    out = c.patch(f"/memo/comments/{cid}", headers=h, json={"status": "resolved"}).json()
    assert out["status"] == "resolved" and out["assignee"] == "priya"

    out = c.patch(f"/memo/comments/{cid}", headers=h, json={"assignee": None, "status": "open"}).json()
    assert out["assignee"] is None and out["status"] == "open"


def test_patch_rejects_unknown_status_and_other_tenants():
    h = new_tenant(c, "mca2")
    v = _version(h)
    cid = c.post(f"/memo/versions/{v}/comments", headers=h, json={"body": "x"}).json()["id"]
    assert c.patch(f"/memo/comments/{cid}", headers=h, json={"status": "done"}).status_code == 422
    other = new_tenant(c, "mca3")
    assert c.patch(f"/memo/comments/{cid}", headers=other, json={"status": "resolved"}).status_code == 404
