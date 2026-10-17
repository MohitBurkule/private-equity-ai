"""Permission sync against WireMock: a SharePoint file's access list decides who can open it, and a re-sync applies
a change at once. Stubs are SYNTHETIC. Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
J = {"Content-Type": "application/json"}
BASE = "/v1.0/sites/SYN-SITE/drive"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def _stub_permissions(wm, emails: list[str], etag: str):
    wm.stub("GET", {"urlPath": f"{BASE}/root/children"}, body=json.dumps({"value": [
        {"id": "T1", "name": "Teaser.csv", "file": {}, "webUrl": "https://synthetic-firm.sharepoint.test/Teaser.csv",
         "eTag": etag}]}), headers=J)
    wm.stub("GET", {"urlPath": f"{BASE}/items/T1/permissions"}, body=json.dumps({"value": [
        {"grantedToV2": {"user": {"email": e}}} for e in emails]}), headers=J)
    wm.stub("GET", {"urlPath": f"{BASE}/items/T1/content"}, body="metric,value\nSYNTHETIC revenue,1\n",
            headers={"Content-Type": "text/csv"})


def _sees(h, doc_id):
    return c.get(f"/documents/{doc_id}/pages/1", headers=h).status_code == 200


def test_access_list_from_sharepoint_through_wiremock(wm, monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({"https://graph.microsoft.com/": wm.base + "/"}))
    _stub_permissions(wm, ["ana@firm.test"], "e1")
    made = c.post("/admin/tenants", json={"name": "perm-wm"}, headers={"X-Admin-Token": "test-admin"}).json()
    tenant, h = made["tenant_id"], {"Authorization": f"Bearer {made['api_key']}"}
    body = {"token": "tok", "options": {"drive": "sites/SYN-SITE/drive"}}
    doc_id = c.post("/connectors/sharepoint/sync", json=body, headers=h).json()["ingested"][0]["document_id"]
    ana = {"Authorization": f"Bearer {c.post(f'/admin/tenants/{tenant}/keys', json={'identity': 'ana@firm.test'}, headers={'X-Admin-Token': 'test-admin'}).json()['api_key']}"}
    ben = {"Authorization": f"Bearer {c.post(f'/admin/tenants/{tenant}/keys', json={'identity': 'ben@firm.test'}, headers={'X-Admin-Token': 'test-admin'}).json()['api_key']}"}
    assert _sees(ana, doc_id) and not _sees(ben, doc_id)

    _stub_permissions(wm, ["ben@firm.test"], "e1")  # same file, new access list at the source
    again = c.post("/connectors/sharepoint/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
    assert not _sees(ana, doc_id) and _sees(ben, doc_id)
