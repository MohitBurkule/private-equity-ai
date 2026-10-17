"""Permission sync: a SharePoint file's access list decides who can find and open it, and a re-sync applies a change
to that list at once, even when the file itself is unchanged. Graph responses are SYNTHETIC."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.test_connectors import fake

c = TestClient(app)
G = "https://graph.microsoft.com/v1.0"
DRIVE = f"{G}/sites/SYN-SITE/drive"


def routes(grantees: list[str], etag: str = "e1"):
    perms = {"value": [{"grantedToV2": {"user": {"email": e}}} for e in grantees]
             + [{"grantedToV2": {"group": {"displayName": "SYN Group"}}}]}  # group grants carry no email, so are skipped
    return {
        f"{DRIVE}/root/children": json.dumps({"value": [
            {"id": "T1", "name": "Teaser.csv", "file": {}, "webUrl": "https://sp.test/Teaser.csv", "eTag": etag}]}).encode(),
        f"{DRIVE}/items/T1/permissions": json.dumps(perms).encode(),
        f"{DRIVE}/items/T1/content": b"metric,value\nSYNTHETIC revenue,1\n",
    }


def key(h, tenant, identity=None):  # h is unused: keys are created with the admin token
    body = {"identity": identity} if identity else {}
    r = c.post(f"/admin/tenants/{tenant}/keys", json=body, headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def sees(h, doc_id=None):
    if doc_id:
        return c.get(f"/documents/{doc_id}/pages/1", headers=h).status_code == 200
    return bool(c.get("/search", params={"q": "revenue"}, headers=h).json())


def test_access_list_gates_search_and_open_and_resync_revokes(monkeypatch):
    made = c.post("/admin/tenants", json={"name": "perm-sync"}, headers={"X-Admin-Token": "test-admin"})
    tenant = made.json()["tenant_id"]
    h = {"Authorization": f"Bearer {made.json()['api_key']}"}
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(routes(["ana@firm.test"])))
    body = {"token": "tok", "options": {"drive": "sites/SYN-SITE/drive"}}
    first = c.post("/connectors/sharepoint/sync", json=body, headers=h)
    assert first.status_code == 200, first.text
    doc_id = first.json()["ingested"][0]["document_id"]
    ana = key(h, tenant, "Ana@Firm.test")
    ben = key(h, tenant, "ben@firm.test")
    nobody = key(h, tenant)
    assert sees(ana) and sees(ana, doc_id)
    assert not sees(ben) and not sees(ben, doc_id)
    assert not sees(nobody) and not sees(nobody, doc_id)

    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(routes(["ben@firm.test"])))
    again = c.post("/connectors/sharepoint/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
    assert not sees(ana, doc_id)  # revoked by the re-sync
    assert sees(ben, doc_id)
