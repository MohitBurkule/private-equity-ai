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
    assert r["gmail"] == "live" and r["salesforce"] == "live" and r["intralinks"] == "live" and len(r) >= 15


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


def test_slack_channel_csv_and_errors():
    import pytest

    from app.connectors.base import ConnectorError
    from app.connectors.slack import Slack
    ok = fake({"https://slack.com/api/conversations.list": {"ok": True, "channels": [{"id": "C1", "name": "deal-atlas", "is_member": True}, {"id": "C2", "name": "x", "is_member": False}]},
               "https://slack.com/api/conversations.history?channel=C1": {"ok": True, "messages": [
                   {"type": "message", "ts": "1.0", "user": "U1", "text": "Revenue 12m"}, {"type": "message", "subtype": "channel_join", "ts": "2.0"}]}})
    it = list(Slack("tok", ok, team="T1").items())
    assert len(it) == 1 and b"Revenue 12m" in it[0].data and b"channel_join" not in it[0].data and it[0].url.endswith("/T1/C1")
    bad = fake({"https://slack.com/api/conversations.list": {"ok": False, "error": "invalid_auth"}})
    with pytest.raises(ConnectorError):
        list(Slack("tok", bad).items())


def test_saved_connection_encrypts_token_and_runs_due(monkeypatch):
    from cryptography.fernet import Fernet
    h = new_tenant(c, "conn")
    monkeypatch.delenv("CONNECTOR_KEY", raising=False)
    body = {"connector": "gmail", "token": "tok", "deal": "atlas", "interval_minutes": 10}
    assert c.post("/connections", json=body, headers=h).status_code == 503  # no key = refuse
    monkeypatch.setenv("CONNECTOR_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    r = c.post("/connections", json=body, headers=h)
    assert r.status_code == 201
    cid = r.json()["id"]
    from app.connectors import vault
    blob = vault.seal("tok")
    assert "tok" not in blob and vault.unseal(blob) == "tok"
    assert c.post("/connections/run-due", headers=h).json()["ran"][0]["status"].startswith("ok: 1 new")
    assert c.post("/connections/run-due", headers=h).json()["ran"] == []  # interval not elapsed
    assert c.post(f"/connections/{cid}/sync", headers=h).json()["unchanged"] == 1
    assert c.get("/connections", headers=h).json()[0]["last_status"].startswith("ok")
    assert "token" not in c.get("/connections", headers=h).text
    assert c.post("/connections", json={**body, "interval_minutes": 1}, headers=h).status_code == 422


def test_dataroom_export_zip_keeps_folders_and_checks_host():
    import io
    import zipfile

    import pytest

    from app.connectors.base import ConnectorError
    from app.connectors.dataroom import Datasite, Intralinks
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Legal/nda.eml", eml("NDA", "signed"))
    url = "https://acme.intralinks.com/export/room1.zip"
    it = list(Intralinks("tok", fake({url: buf.getvalue()}), export_url=url, room="Atlas").items())
    assert it[0].name == "Atlas.zip" and it[0].url == "https://acme.intralinks.com/"
    with pytest.raises(ConnectorError):
        list(Datasite("tok", fake({}), export_url="https://evil.example.com/x.zip").items())
    with pytest.raises(ConnectorError):
        list(Datasite("tok", fake({"https://x.datasite.com/e": b"<html>"}), export_url="https://x.datasite.com/e").items())


def test_dataroom_sync_expands_archive_with_walls(monkeypatch):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Legal/nda.eml", eml("NDA", "signed"))
    url = "https://acme.datasite.com/export/room1.zip"
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({url: buf.getvalue()}))
    h = new_tenant(c, "dr")
    body = {"token": "tok", "deal": "atlas", "options": {"export_url": url, "room": "Atlas"}}
    r = c.post("/connectors/datasite/sync", json=body, headers=h).json()
    assert r["ingested"] and r["ingested"][0]["source_url"] == "https://acme.datasite.com/"
    assert r["ingested"][0]["filename"] == "Legal/nda.eml"


def test_linkedin_export_import_is_walled_and_idempotent(monkeypatch):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Connections.csv", "First Name,Last Name,Company,Position\nAda,Lovelace,Atlas Capital,Partner\n")
        z.writestr("readme.txt", "ignored")
    payload = buf.getvalue()
    h = new_tenant(c, "li")
    r = c.post("/connectors/linkedin/import", files={"file": ("export.zip", payload, "application/zip")},
               data={"deal": "atlas"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["ingested"][0]["source_url"] == "https://www.linkedin.com/"
    again = c.post("/connectors/linkedin/import", files={"file": ("export.zip", payload, "application/zip")},
                   data={"deal": "atlas"}, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
    bad = c.post("/connectors/linkedin/import", files={"file": ("x.zip", b"not a zip", "application/zip")},
                 data={"deal": "atlas"}, headers=h)
    assert bad.status_code == 422
    assert any(x["name"] == "linkedin" and x["status"] == "live" for x in c.get("/connectors", headers=h).json())


OAUTH_ENV = {
    "OAUTH_STATE_SECRET": "s" * 40,
    "OAUTH_REDIRECT_BASE": "https://api.example.test",
    "OAUTH_GMAIL_CLIENT_ID": "cid",
    "OAUTH_GMAIL_CLIENT_SECRET": "csec",
    "OAUTH_GMAIL_AUTH_URL": "https://accounts.example.test/auth",
    "OAUTH_GMAIL_TOKEN_URL": "https://accounts.example.test/token",
}


def _oauth_env(monkeypatch):
    for k, v in OAUTH_ENV.items():
        monkeypatch.setenv(k, v)


def test_oauth_start_callback_then_refresh_on_sync(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from cryptography.fernet import Fernet

    from app.connectors import oauth, vault
    from app.models import Connection
    from app.rls import bind_tenant
    _oauth_env(monkeypatch)
    monkeypatch.setenv("CONNECTOR_KEY", Fernet.generate_key().decode())
    h = new_tenant(c, "oa")
    r = c.post("/oauth/gmail/start", json={"deal": "atlas", "interval_minutes": 10}, headers=h)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["authorize_url"]).query)
    assert q["client_id"] == ["cid"] and q["redirect_uri"] == ["https://api.example.test/oauth/gmail/callback"]
    state = q["state"][0]

    calls = []
    eml_bytes = eml("oauth", "hello")
    gmail_api = {
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/g1": {"raw": base64.urlsafe_b64encode(eml_bytes).decode().rstrip("="), "internalDate": "1"},
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?": {"messages": [{"id": "g1"}]},
    }

    def http(url, headers):
        if url.startswith("https://accounts.example.test/token"):
            from urllib.parse import parse_qs as pq
            form = {k: v[0] for k, v in pq(headers["X-Post-Body"]).items()}
            calls.append(form)
            if form["grant_type"] == "authorization_code":
                return json.dumps({"access_token": "AT1", "refresh_token": "RT1"}).encode()
            return json.dumps({"access_token": "AT2", "refresh_token": "RT2"}).encode()
        assert headers["Authorization"] == "Bearer AT2"
        for k, v in gmail_api.items():
            if url.startswith(k):
                return v if isinstance(v, bytes) else json.dumps(v).encode()
        raise AssertionError(url)

    monkeypatch.setattr(m, "CONNECTOR_HTTP", http)
    cb = c.get("/oauth/gmail/callback", params={"code": "auth-code", "state": state})
    assert cb.status_code == 201, cb.text
    cid = cb.json()["id"]
    assert calls[0]["grant_type"] == "authorization_code" and calls[0]["code"] == "auth-code"
    db = m.SessionLocal()
    bind_tenant(db, oauth.verify_state(state)["tenant"])  # RLS hides rows outside the tenant binding
    row = db.get(Connection, cid)
    assert "RT1" not in row.token_sealed and vault.unseal(row.token_sealed) == "RT1"
    db.close()
    synced = c.post(f"/connections/{cid}/sync", headers=h)
    assert synced.status_code == 200, synced.text
    assert calls[-1]["grant_type"] == "refresh_token" and calls[-1]["refresh_token"] == "RT1"
    db = m.SessionLocal()
    bind_tenant(db, oauth.verify_state(state)["tenant"])
    assert vault.unseal(db.get(Connection, cid).token_sealed) == "RT2"  # rotated token re-sealed
    db.close()


def test_oauth_rejects_tampered_expired_and_cross_connector_state(monkeypatch):
    import time as _t

    from app.connectors import oauth
    _oauth_env(monkeypatch)
    h = new_tenant(c, "oa2")
    good = oauth.sign_state({"tenant": "t", "key": "k", "connector": "gmail", "deal": None, "interval": None, "options": {}})
    monkeypatch.setattr(m, "CONNECTOR_HTTP", lambda u, hd: json.dumps({"access_token": "x"}).encode())
    assert c.get("/oauth/gmail/callback", params={"code": "c", "state": good[:-2] + "00"}).status_code == 400
    expired = oauth.sign_state({"tenant": "t", "key": "k", "connector": "gmail", "options": {}}, now=_t.time() - 3600)
    assert c.get("/oauth/gmail/callback", params={"code": "c", "state": expired}).status_code == 400
    other = oauth.sign_state({"tenant": "t", "key": "k", "connector": "box", "options": {}})
    assert c.get("/oauth/gmail/callback", params={"code": "c", "state": other}).status_code == 400
    assert c.post("/oauth/gmail/start", json={}, headers=h).status_code == 200
    monkeypatch.delenv("OAUTH_GMAIL_CLIENT_ID")
    assert c.post("/oauth/gmail/start", json={}, headers=h).status_code == 503


def test_oauth_needs_refresh_token_at_consent(monkeypatch):
    from app.connectors import oauth
    _oauth_env(monkeypatch)
    monkeypatch.setenv("CONNECTOR_KEY", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
    state = oauth.sign_state({"tenant": "t", "key": "k", "connector": "gmail", "options": {}})
    monkeypatch.setattr(m, "CONNECTOR_HTTP", lambda u, hd: json.dumps({"access_token": "AT"}).encode())
    r = c.get("/oauth/gmail/callback", params={"code": "c", "state": state})
    assert r.status_code == 400 and "refresh token" in r.json()["detail"]
