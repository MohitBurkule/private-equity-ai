"""Memo sign-off: a named approver and a timestamp per saved version. SYNTHETIC entity name."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _version(h, entity="Synth Target"):
    return c.post("/memo/versions", params={"entity": entity}, headers=h).json()["id"]


def test_signoff_records_approver_and_time_and_is_idempotent():
    h = new_tenant(c, "signoff")
    vid = _version(h)
    first = c.post(f"/memo/versions/{vid}/signoff", headers=h)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["approver"] and body["signed_at"]
    again = c.post(f"/memo/versions/{vid}/signoff", headers=h).json()
    assert again == body
    items = c.get(f"/memo/versions/{vid}/signoffs", headers=h).json()["items"]
    assert items == [body]


def test_open_comment_blocks_signoff_until_resolved():
    h = new_tenant(c, "signoff-open")
    vid = _version(h, "Synth Two")
    cid = c.post(f"/memo/versions/{vid}/comments", json={"body": "check the EBITDA source"}, headers=h).json()["id"]
    blocked = c.post(f"/memo/versions/{vid}/signoff", headers=h)
    assert blocked.status_code == 409
    c.patch(f"/memo/comments/{cid}", json={"status": "resolved"}, headers=h)
    assert c.post(f"/memo/versions/{vid}/signoff", headers=h).status_code == 201


def test_other_tenant_cannot_sign_or_read():
    h = new_tenant(c, "signoff-owner")
    vid = _version(h, "Synth Three")
    other = new_tenant(c, "signoff-other")
    assert c.post(f"/memo/versions/{vid}/signoff", headers=other).status_code == 404
    assert c.get(f"/memo/versions/{vid}/signoffs", headers=other).status_code == 404
