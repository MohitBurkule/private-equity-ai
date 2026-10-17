"""Outlook (Microsoft Graph) mail → sync → DD document, with the citation back to the message's webLink.
Graph is answered by a fake HTTP layer shaped like the real API (paged message list, raw MIME per message),
so the sync runs through the same code path a firm tenant uses. A repeat sync must store nothing new."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import eml, fake

c = TestClient(app)
G = "https://graph.microsoft.com/v1.0"
WEB_LINK = "https://outlook.office.com/mail/id/AAMkAGI1"


def _routes() -> dict:
    listing = {"value": [{"id": "AAMkAGI1", "webLink": WEB_LINK, "lastModifiedDateTime": "2026-10-01T09:00:00Z"}]}
    return {
        f"{G}/me/messages?": json.dumps(listing).encode(),
        f"{G}/me/messages/AAMkAGI1/$value": eml("Project Atlas CIM", "Revenue was 1,234 in FY24."),
    }


def test_outlook_mail_becomes_a_document_and_resyncs_clean(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(_routes()))
    h = new_tenant(c, "outlook-flow")
    body = {"token": "tok", "deal": "atlas"}
    first = c.post("/connectors/outlook/sync", json=body, headers=h)
    assert first.status_code == 200, first.text
    (item,) = first.json()["ingested"]
    assert item["filename"].endswith(".eml") and item["source_url"] == WEB_LINK
    docs = c.get("/documents", headers=h).json()
    assert any(d["id"] == item["document_id"] for d in docs)

    again = c.post("/connectors/outlook/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
