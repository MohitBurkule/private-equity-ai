"""DocuSign Connect webhook: an envelope status change moves the matching deal, and only a correctly signed body
is read. Signature is base64 HMAC-SHA256 over the raw body, as DocuSign sends it in X-DocuSign-Signature-1."""
import base64
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
KEY = "synthetic-connect-key"


def _sign(raw: bytes, key: str = KEY) -> str:
    return base64.b64encode(hmac.new(key.encode(), raw, hashlib.sha256).digest()).decode()


def _post(tid: str, payload: dict, sig: str | None = None):
    raw = json.dumps(payload).encode()
    return c.post(f"/webhooks/docusign?tenant={tid}", content=raw,
                  headers={"Content-Type": "application/json",
                           "X-DocuSign-Signature-1": _sign(raw) if sig is None else sig})


def _setup(monkeypatch, name):
    monkeypatch.setenv("DOCUSIGN_CONNECT_HMAC_KEY", KEY)
    t = c.post("/admin/tenants", json={"name": name + "-t"}, headers={"X-Admin-Token": "test-admin"}).json()
    admin = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=admin, json={"name": "Atlas"})
    c.patch("/deals/Atlas", headers=admin, json={"stage": "loi"})
    return t["tenant_id"], admin


def test_signed_completed_envelope_moves_the_deal(monkeypatch):
    tid, admin = _setup(monkeypatch, "connect-ok")
    r = _post(tid, {"envelopeId": "C1", "status": "completed", "emailSubject": "Atlas LOI"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == {"deal": "Atlas", "stage_before": "loi", "stage_after": "signed"}
    assert next(d["stage"] for d in c.get("/deals", headers=admin).json() if d["name"] == "Atlas") == "signed"


def test_bad_or_missing_signature_changes_nothing(monkeypatch):
    tid, admin = _setup(monkeypatch, "connect-bad")
    payload = {"envelopeId": "C2", "status": "completed", "emailSubject": "Atlas LOI"}
    assert _post(tid, payload, sig=_sign(b"other body")).status_code == 401
    assert _post(tid, payload, sig="").status_code == 401
    assert next(d["stage"] for d in c.get("/deals", headers=admin).json() if d["name"] == "Atlas") == "loi"


def test_unconfigured_key_and_unknown_tenant_are_refused(monkeypatch):
    monkeypatch.delenv("DOCUSIGN_CONNECT_HMAC_KEY", raising=False)
    assert _post("nope", {"envelopeId": "C3", "status": "completed", "emailSubject": "x"},
                 sig="").status_code == 503
    monkeypatch.setenv("DOCUSIGN_CONNECT_HMAC_KEY", KEY)
    assert _post("nope", {"envelopeId": "C3", "status": "completed", "emailSubject": "x"}).status_code == 404
