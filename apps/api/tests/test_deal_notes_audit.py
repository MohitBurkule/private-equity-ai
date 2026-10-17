from fastapi.testclient import TestClient

from app.audit import verify_chain
from app.main import SessionLocal, app
from tests.test_mnpi_docs import ADMIN
from tests.test_oidc import _sso, _token

c = TestClient(app)


def _tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    return t["tenant_id"], {"Authorization": f"Bearer {t['api_key']}"}


def test_shared_notes_follow_deal_visibility_and_are_audited(monkeypatch):
    _sso(monkeypatch)
    tid, creator = _tenant("notes")
    assert c.post("/deals", headers=creator, json={"name": "Atlas"}).status_code == 201
    assert c.post("/deals", headers=creator, json={"name": "Hidden", "mnpi": True}).status_code == 201
    note = c.post("/deals/Atlas/notes", headers=creator, json={"body": "Mgmt call Tues"})
    assert note.status_code == 201 and note.json()["body"] == "Mgmt call Tues"
    assert [n["body"] for n in c.get("/deals/Atlas/notes", headers=creator).json()] == ["Mgmt call Tues"]
    scoped = {"Authorization": f"Bearer {_token(tenant=tid, role='analyst', sub='nina', deals=['Other'])}"}
    assert c.get("/deals/Atlas/notes", headers=scoped).status_code == 404
    assert c.post("/deals/Atlas/notes", headers=scoped, json={"body": "x"}).status_code == 404
    outsider = {"Authorization": f"Bearer {_token(tenant=tid, role='partner', sub='olga')}"}
    assert c.post("/deals", headers=creator, json={"name": "Quiet"}).status_code == 201
    assert c.get("/deals/Hidden/notes", headers=outsider).status_code == 404  # MNPI deal hidden from outsider
    assert c.post("/deals/Atlas/notes", headers=creator, json={"body": ""}).status_code == 422


def test_audit_trail_is_whole_tenant_only_and_filters_by_action(monkeypatch):
    _sso(monkeypatch)
    tid, creator = _tenant("audit-read")
    assert c.post("/deals", headers=creator, json={"name": "Atlas"}).status_code == 201
    c.post("/deals/Atlas/notes", headers=creator, json={"body": "one"})
    rows = c.get("/audit?action=deal.note", headers=creator).json()["items"]
    assert len(rows) == 1 and rows[0]["payload"] == {"deal": "Atlas", "id": rows[0]["payload"]["id"]}
    scoped = {"Authorization": f"Bearer {_token(tenant=tid, role='analyst', sub='ruth', deals=['Atlas'])}"}
    assert c.get("/audit", headers=scoped).status_code == 403
    db = SessionLocal()
    try:
        assert verify_chain(db, tid)[0] is True
    finally:
        db.close()
