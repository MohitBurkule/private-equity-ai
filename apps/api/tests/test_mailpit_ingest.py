"""Mailpit as a document source. Replays a synthetic Mailpit API (list, then raw message); no real mail."""
import json
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.connectors.base import ConnectorError
from app.connectors.mailpit import Mailpit
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
BASE = "http://localhost:8025"


def raw_mail(subject, body):
    e = EmailMessage()
    e["From"], e["To"], e["Subject"], e["Date"] = "a@x.com", "ic@firm.test", subject, "Mon, 1 Jan 2024 10:00:00 +0000"
    e.set_content(body)
    return bytes(e)


class FakeMailpit:
    def __init__(self, messages):
        self.messages = messages  # {ID: raw bytes}

    def __call__(self, url, headers):
        if url.startswith(f"{BASE}/api/v1/messages?"):
            return json.dumps({"messages": [{"ID": k} for k in self.messages]}).encode()
        if url.startswith(f"{BASE}/api/v1/message/") and url.endswith("/raw"):
            return self.messages[url.split("/")[-2]]
        raise AssertionError(f"unrouted {url}")


def test_items_cite_mailpit_view_and_skip_nothing():
    fake = FakeMailpit({"ab12": raw_mail("Atlas CIM", "Revenue was 1,234 in FY24.")})
    (item,) = list(Mailpit("local", fake).items())
    assert item.external_id == "mailpit:ab12"
    assert item.name == "mailpit-ab12.eml"
    assert item.url == f"{BASE}/view/ab12"
    assert item.data.startswith(b"From:")


def test_refuses_non_local_base():
    with pytest.raises(ConnectorError):
        list(Mailpit("local", FakeMailpit({}), base="https://mail.example.com").items())


def test_sync_ingests_emails_with_source_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", FakeMailpit({"ab12": raw_mail("Atlas CIM", "Revenue was 1,234 in FY24.")}))
    h = new_tenant(c, "mp")
    r = c.post("/connectors/mailpit/sync", json={"token": "local", "deal": "atlas"}, headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()["ingested"][0]
    assert doc["source_url"] == f"{BASE}/view/ab12"
    again = c.post("/connectors/mailpit/sync", json={"token": "local", "deal": "atlas"}, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1
