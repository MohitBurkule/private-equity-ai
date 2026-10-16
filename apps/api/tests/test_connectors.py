"""Connector tests replay SYNTHETIC responses shaped like the Gmail and Graph APIs (no real mailbox)."""
import base64
import json
from email.message import EmailMessage

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def eml(subject: str, body: str) -> bytes:
    e = EmailMessage()
    e["From"], e["To"], e["Subject"], e["Date"] = "a@x.com", "b@x.com", subject, "Mon, 1 Jan 2024 10:00:00 +0000"
    e.set_content(body)
    return bytes(e)


def fake(routes):
    def http(url, headers):
        assert headers["Authorization"] == "Bearer tok"
        for k, v in routes.items():
            if url.startswith(k):
                return v if isinstance(v, bytes) else json.dumps(v).encode()
        raise AssertionError(f"unrouted {url}")
    return http


def gmail_routes():
    raw = base64.urlsafe_b64encode(eml("Atlas CIM", "Revenue was 1,234 in FY24.")).decode().rstrip("=")
    return {"https://gmail.googleapis.com/gmail/v1/users/me/messages/g1": {"raw": raw, "internalDate": "1700"},
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {"messages": [{"id": "g1"}]}}


def test_catalog_status():
    h = new_tenant(c, "cat")
    r = {x["name"]: x["status"] for x in c.get("/connectors", headers=h).json()}
    assert r["gmail"] == "live" and r["salesforce"] == "live" and r["slack"] == "planned" and len(r) >= 15


def test_gmail_sync_cites_source_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    h = new_tenant(c, "gm")
    r = c.post("/connectors/gmail/sync", json={"token": "tok", "deal": "atlas"}, headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()["ingested"][0]
    assert doc["source_url"] == "https://mail.google.com/mail/u/0/#all/g1"
    s = c.get(f"/documents/{doc['document_id']}/source", headers=h).json()
    assert s["connector"] == "gmail" and s["url"] == doc["source_url"]
    again = c.post("/connectors/gmail/sync", json={"token": "tok", "deal": "atlas"}, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1


def test_deal_wall_blocks_out_of_scope_sync(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    import pytest

    from app.acl import Principal
    from app.connectors.gmail import Gmail
    from app.connectors.sync import sync
    p = Principal(tenant="t", deals=frozenset({"other"}))
    with pytest.raises(PermissionError):
        sync(None, p, Gmail("tok", fake(gmail_routes())), "atlas")
    with pytest.raises(PermissionError):
        sync(None, p, Gmail("tok", fake(gmail_routes())), None)


def test_graph_drive_recurses_and_preserves_path(monkeypatch):
    G = "https://graph.microsoft.com/v1.0/me/drive"
    xl = eml("x", "y")
    routes = {
        f"{G}/root/children": {"value": [{"id": "f1", "name": "Legal", "folder": {}}]},
        f"{G}/items/f1/children": {"value": [{"id": "d1", "name": "note.eml", "file": {}, "webUrl": "https://sp/x", "eTag": "e1"}]},
        f"{G}/items/d1/content": xl,
    }
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(routes))
    h = new_tenant(c, "sp")
    r = c.post("/connectors/sharepoint/sync", json={"token": "tok", "deal": "atlas"}, headers=h).json()
    assert r["ingested"][0]["source_url"] == "https://sp/x"
    assert r["ingested"][0]["filename"].startswith("Legal/note.eml")


def test_unknown_connector_and_bad_response(monkeypatch):
    h = new_tenant(c, "bad")
    assert c.post("/connectors/nope/sync", json={"token": "t"}, headers=h).status_code == 404
    monkeypatch.setattr(m, "CONNECTOR_HTTP", lambda u, hd: b"<html>")
    assert c.post("/connectors/gmail/sync", json={"token": "t"}, headers=h).status_code == 502


def test_gdrive_exports_native_sheets_and_recurses(monkeypatch):
    D = "https://www.googleapis.com/drive/v3/files"
    plain = eml("drv", "hello")
    routes = {
        f"{D}/s1/export": plain, f"{D}/p1?alt=media": plain,
        D + "?q=%27sub%27": {"files": [{"id": "p1", "name": "n.eml", "mimeType": "message/rfc822", "webViewLink": "https://d/p1", "modifiedTime": "t1"}]},
        D + "?q=%27root%27": {"files": [
            {"id": "sub", "name": "Legal", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "s1", "name": "Model", "mimeType": "application/vnd.google-apps.spreadsheet", "webViewLink": "https://d/s1", "modifiedTime": "t0"},
            {"id": "f", "name": "Form", "mimeType": "application/vnd.google-apps.form"}]},
    }
    from app.connectors.files import GoogleDrive
    names = [(i.name, i.url) for i in GoogleDrive("tok", fake(routes)).items()]
    assert ("Model.xlsx", "https://d/s1") in names and ("Legal/n.eml", "https://d/p1") in names
    assert len(names) == 2  # form skipped


def test_box_and_dropbox_paths():
    from app.connectors.files import Box, Dropbox
    plain = eml("b", "x")
    box = fake({"https://api.box.com/2.0/folders/0/items": {"total_count": 1, "entries": [{"id": "9", "name": "a.eml", "type": "file", "etag": "3"}]},
                "https://api.box.com/2.0/files/9/content": plain})
    it = list(Box("tok", box).items())
    assert it[0].url == "https://app.box.com/file/9" and it[0].version == "3"

    def dbx(url, headers):
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("list_folder"):
            return json.dumps({"entries": [{".tag": "file", "id": "id:1", "path_display": "/Deals/a.eml", "rev": "r1"}], "has_more": False}).encode()
        assert json.loads(headers["Dropbox-API-Arg"]) == {"path": "id:1"}
        return plain
    d = list(Dropbox("tok", dbx).items())
    assert d[0].name == "Deals/a.eml" and d[0].url.endswith("/Deals/a.eml")


def test_crm_connectors_make_cited_csv(monkeypatch):
    from app.connectors.crm import Affinity, DealCloud, HubSpot, Salesforce, to_csv
    assert to_csv([{"a": 1, "n": {"x": 1}, "b": None}, {"a": 2, "c": "z"}]).decode().splitlines() == ["a,b,c", "1,,", "2,,z"]
    sf = fake({"https://acme.my.salesforce.com/services/data/v60.0/query": {"records": [
        {"attributes": {"type": "Account"}, "Id": "1", "Name": "Atlas", "AnnualRevenue": 5000000}]}})
    it = list(Salesforce("tok", sf, instance_url="https://acme.my.salesforce.com", objects="Account").items())
    assert b"Atlas" in it[0].data and it[0].url.endswith("/lightning/o/Account/list")
    hs = fake({"https://api.hubapi.com/crm/v3/objects/deals": {"results": [{"id": "9", "properties": {"dealname": "Atlas"}}]}})
    assert b"dealname" in next(iter(HubSpot("tok", hs, objects="deals").items())).data

    def aff(url, headers):
        assert headers["Authorization"] == "Basic " + base64.b64encode(b":tok").decode()
        return json.dumps({"organizations": [{"id": 1, "name": "Atlas"}]}).encode()
    assert b"Atlas" in next(iter(Affinity("tok", aff, objects="organizations").items())).data
    dc = fake({"https://acme.dealcloud.com/api/rest/v4/data/entrydata/rows/Company": {"rows": [{"EntryId": 1, "Name": "Atlas"}]}})
    assert list(DealCloud("tok", dc, site="acme.dealcloud.com", objects="Company").items())


def test_crm_rejects_foreign_hosts_and_sync_is_idempotent(monkeypatch):
    import pytest

    from app.connectors.base import ConnectorError
    from app.connectors.crm import DealCloud, Salesforce
    with pytest.raises(ConnectorError):
        list(Salesforce("t", fake({}), instance_url="https://evil.example.com", objects="Account").items())
    with pytest.raises(ConnectorError):
        list(DealCloud("t", fake({}), site="evil.com", objects="x").items())
    hs = fake({"https://api.hubapi.com/crm/v3/objects/deals": {"results": [{"id": "9", "properties": {"dealname": "Atlas", "amount": "100"}}]}})
    monkeypatch.setattr(m, "CONNECTOR_HTTP", hs)
    h = new_tenant(c, "crm")
    body = {"token": "tok", "deal": "atlas", "options": {"objects": "deals"}}
    r = c.post("/connectors/hubspot/sync", json=body, headers=h).json()
    assert len(r["ingested"]) == 1
    assert c.post("/connectors/hubspot/sync", json=body, headers=h).json()["unchanged"] == 1
