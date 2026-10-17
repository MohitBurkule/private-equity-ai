from fastapi.testclient import TestClient

from app.acl import CAPABILITIES, ROLES, Principal
from app.main import app

c = TestClient(app)


def _key(role: str, tenant_id: str | None = None) -> dict:
    if tenant_id is None:
        t = c.post("/admin/tenants", json={"name": f"role-{role}"}, headers={"X-Admin-Token": "test-admin"}).json()
        tenant_id = t["tenant_id"]
    k = c.post(f"/admin/tenants/{tenant_id}/keys", json={"role": role}, headers={"X-Admin-Token": "test-admin"})
    return {"Authorization": f"Bearer {k.json()['api_key']}"}


def test_capability_table_matches_roles():
    assert set(CAPABILITIES["write"]) | set(CAPABILITIES["govern"]) <= set(ROLES)
    assert Principal("t", "compliance").can("govern") and not Principal("t", "compliance").can("write")
    assert not Principal("t", "ir").can("write") and not Principal("t", "ir").can("govern")


def _tenant_of(headers: dict) -> str:
    from app.auth import hash_key
    from app.main import SessionLocal
    from app.models import ApiKey

    with SessionLocal() as db:
        return db.get(ApiKey, hash_key(headers["Authorization"][7:])).tenant_id


def test_associate_writes_deals_but_cannot_hold_or_flag(monkeypatch):
    a = _key("associate")
    assert c.post("/deals", headers=a, json={"name": "Assoc"}).status_code == 201
    assert c.patch("/deals/Assoc", headers=a, json={"legal_hold": True}).status_code == 403
    assert c.patch("/deals/Assoc", headers=a, json={"mnpi": True}).status_code == 403
    assert c.delete("/deals/Assoc", headers=a).status_code == 403


def test_compliance_holds_and_flags_but_cannot_upload():
    admin = _key("admin")
    comp = _key("compliance", _tenant_of(admin))
    assert c.post("/deals", headers=admin, json={"name": "Comp"}).status_code == 201
    assert c.patch("/deals/Comp", headers=comp, json={"legal_hold": True}).status_code == 200
    assert c.post("/documents", headers=comp, files={"file": ("a.txt", b"hi", "text/plain")}).status_code == 403


def test_ir_is_read_only():
    ir = _key("ir")
    assert c.get("/deals", headers=ir).status_code == 200
    assert c.post("/deals", headers=ir, json={"name": "IR"}).status_code == 403
