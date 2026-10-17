from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_save_versions_comment_and_diff_between_them():
    h = new_tenant(c, "memo-versions")
    v1 = c.post("/memo/versions?entity=Acme", headers=h).json()
    v2 = c.post("/memo/versions?entity=Acme", headers=h).json()
    assert (v1["number"], v2["number"]) == (1, 2)
    assert c.get("/memo/versions?entity=Acme", headers=h).json()["items"][1]["number"] == 2
    cm = c.post(f"/memo/versions/{v2['id']}/comments", headers=h, json={"body": "Check the margin line"})
    assert cm.status_code == 201
    got = c.get(f"/memo/versions/{v2['id']}", headers=h).json()
    assert got["markdown"].startswith("# Acme") and got["comments"][0]["body"] == "Check the margin line"
    d = c.get(f"/memo/versions/diff?from_id={v1['id']}&to_id={v2['id']}", headers=h).json()
    assert d["changed"] is False and (d["from"], d["to"]) == (1, 2)


def test_versions_are_tenant_scoped_and_entity_scoped():
    h = new_tenant(c, "memo-tenant-a")
    other = new_tenant(c, "memo-tenant-b")
    a = c.post("/memo/versions?entity=Acme", headers=h).json()
    assert c.get(f"/memo/versions/{a['id']}", headers=other).status_code == 404
    assert c.post(f"/memo/versions/{a['id']}/comments", headers=other, json={"body": "x"}).status_code == 404
    b = c.post("/memo/versions?entity=Beta", headers=h).json()
    assert c.get(f"/memo/versions/diff?from_id={a['id']}&to_id={b['id']}", headers=h).status_code == 404


def test_comment_body_is_required():
    h = new_tenant(c, "memo-empty-comment")
    v = c.post("/memo/versions?entity=Acme", headers=h).json()
    assert c.post(f"/memo/versions/{v['id']}/comments", headers=h, json={"body": ""}).status_code == 422
