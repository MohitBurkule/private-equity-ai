from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_note_edit_keeps_audit_trail_and_is_scoped():
    h = new_tenant(c, "noteedit")
    assert c.post("/deals", headers=h, json={"name": "Note Deal"}).status_code in (200, 201)
    nid = c.post("/deals/Note Deal/notes", headers=h, json={"body": "first draft"}).json()["id"]
    r = c.patch(f"/deals/Note Deal/notes/{nid}", headers=h, json={"body": "  revised  "})
    assert r.status_code == 200 and r.json()["body"] == "revised" and r.json()["edited_at"]
    trail = c.get("/audit?action=deal.note_edit", headers=h).json()
    items = trail["items"] if isinstance(trail, dict) else trail
    assert items and items[0]["payload"]["before"] == "first draft"
    other = new_tenant(c, "noteedit2")
    assert c.patch(f"/deals/Note Deal/notes/{nid}", headers=other, json={"body": "x"}).status_code in (403, 404)
    assert c.patch("/deals/Note Deal/notes/999999", headers=h, json={"body": "x"}).status_code == 404
