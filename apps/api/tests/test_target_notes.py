from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_target_notes_add_edit_audit_and_tenant_scope():
    h = new_tenant(c, "tnotes")
    other = new_tenant(c, "tnotes2")
    assert c.post("/targets", headers=h, json=[{"name": "Note Target Ltd", "source": "manual",
                                                 "source_ref": "NT1"}]).status_code == 201
    tid = next(t["id"] for t in c.get("/targets?q=Note Target", headers=h).json()["items"])
    nid = c.post(f"/targets/{tid}/notes", headers=h, json={"body": "  first look  "}).json()["id"]
    assert c.get(f"/targets/{tid}/notes", headers=h).json()[0]["body"] == "first look"
    r = c.patch(f"/targets/{tid}/notes/{nid}", headers=h, json={"body": "revised"})
    assert r.status_code == 200 and r.json()["edited_at"]
    trail = c.get("/audit?action=target.note_edit", headers=h).json()["items"]
    assert trail and trail[0]["payload"]["before"] == "first look"
    assert c.get(f"/targets/{tid}/notes", headers=other).status_code == 404
    assert c.patch(f"/targets/{tid}/notes/{nid}", headers=other, json={"body": "x"}).status_code == 404
