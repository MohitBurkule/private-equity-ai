"""DocuSign envelopes → deal stage. SYNTHETIC envelopes in the shape documented in app/connectors/docusign.py.
Only a completed envelope whose subject names the deal moves it, and only forward."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://docusign.example.com/synthetic"
URL = f"{BASE}/v2.1/accounts/ACC1/envelopes?from_date=2026-09-01"
ENVELOPES = {"envelopes": [
    {"envelopeId": "E1", "status": "completed", "emailSubject": "Atlas LOI", "completedDateTime": "2026-09-10"},
    {"envelopeId": "E2", "status": "sent", "emailSubject": "Atlas NDA", "completedDateTime": ""},
    {"envelopeId": "E3", "status": "completed", "emailSubject": "Atlasian NDA", "completedDateTime": "2026-09-11"},
    {"envelopeId": "E4", "status": "completed", "emailSubject": "Beacon LOI", "completedDateTime": "2026-09-12"}]}
OPTS = {"base_url": BASE, "account": "ACC1", "from_date": "2026-09-01"}


def _deal(h, name, stage):
    c.post("/deals", headers=h, json={"name": name})
    c.patch(f"/deals/{name}", headers=h, json={"stage": stage})


def _stage_of(name, h):
    return next(d["stage"] for d in c.get("/deals", headers=h).json() if d["name"] == name)


def _sync(h, deal, monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({URL: json.dumps(ENVELOPES).encode()}))
    return c.post("/connectors/docusign/stage-sync", headers=h, json={"token": "tok", "deal": deal, "options": OPTS})


def test_completed_envelope_moves_the_named_deal_to_signed_only(monkeypatch):
    h = new_tenant(c, "docusign-stage")
    _deal(h, "Atlas", "loi")
    out = _sync(h, "Atlas", monkeypatch)
    assert out.status_code == 200, out.text
    assert out.json() == {"deal": "Atlas", "stage_before": "loi", "stage_after": "signed", "envelopes": ["E1"]}
    assert _stage_of("Atlas", h) == "signed"


def test_stage_never_moves_back_and_closed_deals_stay(monkeypatch):
    h = new_tenant(c, "docusign-back")
    _deal(h, "Atlas", "closed")
    out = _sync(h, "Atlas", monkeypatch).json()
    assert out["stage_after"] == "closed" and out["envelopes"] == []


def test_unknown_deal_and_out_of_scope_key_are_refused(monkeypatch):
    t = c.post("/admin/tenants", json={"name": "docusign-scope"}, headers={"X-Admin-Token": "test-admin"}).json()
    admin = {"Authorization": f"Bearer {t['api_key']}"}
    _deal(admin, "Atlas", "loi")
    _deal(admin, "Beacon", "loi")
    assert _sync(admin, "Nowhere", monkeypatch).status_code == 404
    walled = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"deals": ["Atlas"]},
                    headers={"X-Admin-Token": "test-admin"}).json()["api_key"]
    scoped = {"Authorization": f"Bearer {walled}"}
    assert _sync(scoped, "Beacon", monkeypatch).status_code == 403
    assert _sync(scoped, "Atlas", monkeypatch).json()["stage_after"] == "signed"
