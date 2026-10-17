"""Admin view of synced document access lists: admin token only, lists only documents a source restricts, and
never leaks the other tenant's documents."""
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from app.models import Document, DocumentSource
from app.rls import bind_tenant
from tests.helpers import new_tenant_id

ADMIN = {"X-Admin-Token": "test-admin"}
c = TestClient(app)


def _seed(tid: str, doc_id: str, acl: str | None):
    db = m.SessionLocal()
    bind_tenant(db, tid)
    db.add(Document(id=doc_id, tenant_id=tid, sha256=doc_id, filename=f"{doc_id}.pdf", n_pages=1))
    db.flush()
    db.add(DocumentSource(tenant_id=tid, document_id=doc_id, connector="sharepoint", external_id=doc_id,
                          version="1", url="https://example.com/x", acl=acl))
    db.commit()
    db.close()


def test_lists_only_restricted_documents_with_their_grants(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    _h, tid = new_tenant_id(c, "doc-access")
    _seed(tid, "d-restricted", '["ana@firm.example", "group:deal-team"]')
    _seed(tid, "d-open", None)

    r = c.get(f"/admin/tenants/{tid}/document-access", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restricted"] == 1
    (doc,) = body["documents"]
    assert doc["document_id"] == "d-restricted"
    assert doc["grants"] == ["ana@firm.example", "group:deal-team"]
    assert doc["connector"] == "sharepoint"


def test_requires_admin_token_and_known_tenant(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    h, tid = new_tenant_id(c, "doc-access-auth")
    assert c.get(f"/admin/tenants/{tid}/document-access", headers=h).status_code == 403
    assert c.get("/admin/tenants/nope/document-access", headers=ADMIN).status_code == 404
