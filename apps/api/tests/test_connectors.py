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
    assert r["gmail"] == "live" and r["salesforce"] == "planned" and len(r) >= 15


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
