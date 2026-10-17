"""Directory group sync: a key's groups come from its person's directory memberships (Graph memberOf), so a group
grant on a synced document reaches the right people without a hand-kept list. Graph responses are SYNTHETIC."""

import json
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.auth import hash_key, key_id
from app.main import app
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
G = "https://graph.microsoft.com/v1.0"
MEMBER = f"{G}/users/ana%40firm.test/memberOf"
STUBS = Path(__file__).resolve().parents[3] / "deploy" / "mocks" / "wiremock" / "mappings" / "graph-member-of.json"


def _key(tenant, identity):
    return c.post(f"/admin/tenants/{tenant}/keys", json={"identity": identity},
                  headers={"X-Admin-Token": "test-admin"}).json()


def test_memberof_pages_become_the_key_groups(monkeypatch):
    page1 = {"value": [{"@odata.type": "#microsoft.graph.group", "id": "GRP-IC"}],
             "@odata.nextLink": f"{MEMBER}?$skiptoken=2"}
    page2 = {"value": [{"@odata.type": "#microsoft.graph.group", "id": "GRP-DEAL"}]}
    pages = {f"{MEMBER}?$select=id": page1, f"{MEMBER}?$skiptoken=2": page2}  # exact URLs: no prefix matching
    monkeypatch.setattr(m, "CONNECTOR_HTTP", lambda url, headers: json.dumps(pages[url]).encode())
    made = c.post("/admin/tenants", json={"name": "dir-groups"}, headers={"X-Admin-Token": "test-admin"}).json()
    tenant = made["tenant_id"]
    kid = key_id(hash_key(_key(tenant, "ana@firm.test")["api_key"]))
    r = c.post(f"/admin/tenants/{tenant}/keys/{kid}/groups/sync", json={"token": "tok"},
               headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 200, r.text
    assert r.json()["groups"] == ["grp-deal", "grp-ic"]


def test_group_sync_needs_admin_and_an_identity(monkeypatch):
    made = c.post("/admin/tenants", json={"name": "dir-groups-2"}, headers={"X-Admin-Token": "test-admin"}).json()
    tenant = made["tenant_id"]
    r = c.post(f"/admin/tenants/{tenant}/keys/x/groups/sync", json={"token": "tok"})
    assert r.status_code == 403


STUBS = __import__("pathlib").Path(__file__).resolve().parents[3] / "deploy" / "mocks" / "wiremock" / "mappings"


def test_memberof_through_wiremock_follows_paging(monkeypatch):


    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as wm:
        for f in ("graph-member-of.json",):
            for mapping in json.loads((STUBS / f).read_text())["mappings"]:
                req = urllib.request.Request(f"{wm.base}/__admin/mappings", data=json.dumps(mapping).encode(),
                                             method="POST", headers={"content-type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
        monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({"https://graph.microsoft.com/": wm.base + "/"}))
        made = c.post("/admin/tenants", json={"name": "dir-wm"}, headers={"X-Admin-Token": "test-admin"}).json()
        tenant = made["tenant_id"]
        kid = key_id(hash_key(_key(tenant, "ana@firm.test")["api_key"]))
        r = c.post(f"/admin/tenants/{tenant}/keys/{kid}/groups/sync", json={"token": "tok"},
                   headers={"X-Admin-Token": "test-admin"})
        assert r.status_code == 200, r.text
        assert r.json()["groups"] == ["grp-deal", "grp-ic"]
