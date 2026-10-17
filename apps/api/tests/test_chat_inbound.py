"""Slack and Teams inbound: signed requests only, answers with citations, run as the app's key so deal scope and
MNPI walls apply. The model is faked; the signature, scope and reply formats are real."""
import base64
import hashlib
import hmac
import io
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.main as app_main
from app.llm import LLM
from app.main import app

ADMIN = {"X-Admin-Token": "test-admin"}
SLACK_SECRET = "slack-signing-secret"
TEAMS_TOKEN = base64.b64encode(b"teams-outgoing-secret").decode()
c = TestClient(app)


class Cites(LLM):
    def __init__(self, doc_id, quote):
        self.doc_id, self.quote = doc_id, quote

    def complete(self, system, user):
        return json.dumps({"claims": [{"text": "Alpha revenue was 1,234", "doc_id": self.doc_id,
                                       "page": 1, "quote": self.quote}]})


def xlsx(text):
    wb = Workbook()
    wb.active["A1"] = text
    wb.active["B1"] = 1234
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def upload(h, text, deal=None):
    return c.post("/documents", files={"file": (f"{text[:5]}.xlsx", xlsx(text), "x")},
                  data={"deal": deal} if deal else {}, headers=h).json()["id"]


def slack_headers(body: bytes, ts: int | None = None, secret: str = SLACK_SECRET) -> dict:
    ts = str(int(time.time()) if ts is None else ts)
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
            "Content-Type": "application/x-www-form-urlencoded"}


def teams_headers(body: bytes, token_b64: str = TEAMS_TOKEN) -> dict:
    sig = base64.b64encode(hmac.new(base64.b64decode(token_b64), body, hashlib.sha256).digest()).decode()
    return {"Authorization": f"HMAC {sig}", "Content-Type": "application/json"}


@pytest.fixture()
def world(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SLACK_SECRET)
    monkeypatch.setenv("TEAMS_SECURITY_TOKEN", TEAMS_TOKEN)
    t = c.post("/admin/tenants", json={"name": "chat-inbound"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}
    open_key = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "analyst"}, headers=ADMIN).json()["api_key"]
    monkeypatch.setenv("SLACK_INBOUND_API_KEY", open_key)
    monkeypatch.setenv("TEAMS_INBOUND_API_KEY", open_key)
    c.post("/deals", headers=owner, json={"name": "Alpha"})
    c.post("/deals", headers=owner, json={"name": "Secret", "mnpi": True})
    open_doc = upload(owner, "alpha revenue", "Alpha")
    secret_doc = upload(owner, "secret revenue", "Secret")
    return {"owner": owner, "open_key": open_key, "open_doc": open_doc, "secret_doc": secret_doc,
            "tenant": t["tenant_id"]}


def slack_call(body_fields: dict, headers: dict):
    body = urlencode(body_fields).encode()
    return c.post("/chat/slack/inbound", content=body, headers=headers)


def test_signed_slack_question_gets_cited_ephemeral_answer(world, monkeypatch):
    monkeypatch.setattr(app_main, "get_llm", lambda: Cites(world["open_doc"], "Sheet!A1: alpha revenue\nSheet!B1: 1,234"))
    body = urlencode({"text": "what was alpha revenue?"}).encode()
    r = c.post("/chat/slack/inbound", content=body, headers=slack_headers(body))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["response_type"] == "ephemeral"
    assert "Alpha revenue was 1,234" in out["text"] and "p.1" in out["text"]


def test_bad_or_stale_slack_signature_is_refused(world):
    body = urlencode({"text": "alpha revenue 1234?"}).encode()
    assert c.post("/chat/slack/inbound", content=body, headers=slack_headers(body, secret="wrong")).status_code == 401
    assert c.post("/chat/slack/inbound", content=body,
                  headers=slack_headers(body, ts=int(time.time()) - 3600)).status_code == 401


def test_scoped_bot_key_cannot_cite_a_walled_deal(world, monkeypatch):
    scoped = c.post(f"/admin/tenants/{world['tenant']}/keys", json={"role": "analyst", "deals": ["Alpha"]},
                    headers=ADMIN).json()["api_key"]
    monkeypatch.setenv("SLACK_INBOUND_API_KEY", scoped)
    monkeypatch.setattr(app_main, "get_llm", lambda: Cites(world["secret_doc"], "Sheet!A1: alpha revenue\nSheet!B1: 1,234"))
    body = urlencode({"text": "alpha revenue 1234?"}).encode()
    out = c.post("/chat/slack/inbound", content=body, headers=slack_headers(body)).json()
    assert "Alpha revenue" not in out["text"]


def test_teams_mention_is_stripped_and_answer_is_a_message(world, monkeypatch):
    monkeypatch.setattr(app_main, "get_llm", lambda: Cites(world["open_doc"], "Sheet!A1: alpha revenue\nSheet!B1: 1,234"))
    body = json.dumps({"text": "<at>PE Bot</at> what was alpha revenue?"}).encode()
    r = c.post("/chat/teams/inbound", content=body, headers=teams_headers(body))
    assert r.status_code == 200 and r.json()["type"] == "message"
    assert "Alpha revenue was 1,234" in r.json()["text"]
    bad = c.post("/chat/teams/inbound", content=body, headers=teams_headers(body, base64.b64encode(b"x").decode()))
    assert bad.status_code == 401


def test_empty_question_gets_help_and_unknown_app_is_404(world):
    body = urlencode({"text": "   "}).encode()
    r = c.post("/chat/slack/inbound", content=body, headers=slack_headers(body))
    assert r.status_code == 200 and "Ask a question" in r.json()["text"]
    assert c.post("/chat/discord/inbound", content=b"{}").status_code == 404


def test_unconfigured_app_is_503(monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    body = urlencode({"text": "x"}).encode()
    assert c.post("/chat/slack/inbound", content=body, headers={}).status_code == 503
