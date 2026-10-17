"""The document list must not name a document the caller cannot open. A synced source's access list hides the
document from the list as well as from its page, so the filename does not leak."""
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from app.models import Document, DocumentSource
from app.rls import bind_tenant
from tests.helpers import new_tenant_id

ADMIN = {"X-Admin-Token": "test-admin"}
c = TestClient(app)


def _seed(tid: str, name: str, filename: str, acl: str | None) -> str:
    doc_id = f"{name}-{tid}"  # document ids are global, so each tenant's seed gets its own
    db = m.SessionLocal()
    bind_tenant(db, tid)
    db.add(Document(id=doc_id, tenant_id=tid, sha256=doc_id, filename=filename, n_pages=1))
    db.flush()
    db.add(DocumentSource(tenant_id=tid, document_id=doc_id, connector="sharepoint", external_id=doc_id,
                          version="1", url="https://example.com/x", acl=acl))
    db.commit()
    db.close()
    return doc_id


def test_restricted_filename_is_not_listed_and_its_page_is_404(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    _h, tid = new_tenant_id(c, "doc-list-acl")
    secret = _seed(tid, "d-secret", "board-minutes-secret.pdf", '["ana@firm.example"]')
    _seed(tid, "d-open", "public-memo.pdf", None)
    viewer = c.post(f"/admin/tenants/{tid}/keys", json={"role": "analyst", "identity": "bob@firm.example"},
                    headers=ADMIN).json()
    h = {"Authorization": f"Bearer {viewer['api_key']}"}

    names = [d["filename"] for d in c.get("/documents", headers=h).json()]
    assert "public-memo.pdf" in names
    assert "board-minutes-secret.pdf" not in names
    assert c.get(f"/documents/{secret}/pages/1", headers=h).status_code == 404


def test_listed_person_still_sees_the_restricted_filename(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    _h, tid = new_tenant_id(c, "doc-list-acl-ok")
    _seed(tid, "d-secret", "board-minutes-secret.pdf", '["ana@firm.example"]')
    ana = c.post(f"/admin/tenants/{tid}/keys", json={"role": "analyst", "identity": "ana@firm.example"},
                 headers=ADMIN).json()
    h = {"Authorization": f"Bearer {ana['api_key']}"}
    assert "board-minutes-secret.pdf" in [d["filename"] for d in c.get("/documents", headers=h).json()]
