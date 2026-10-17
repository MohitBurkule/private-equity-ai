import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import audit_archive
from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def test_retention_years_is_validated(monkeypatch):
    monkeypatch.delenv("AUDIT_RETENTION_YEARS", raising=False)
    assert audit_archive.retention_years() == 7
    monkeypatch.setenv("AUDIT_RETENTION_YEARS", "0")
    with pytest.raises(ValueError):
        audit_archive.retention_years()
    monkeypatch.setenv("AUDIT_RETENTION_YEARS", "seven")
    with pytest.raises(ValueError):
        audit_archive.retention_years()


def test_cutoff_is_that_many_years_back():
    now = datetime(2030, 1, 1, tzinfo=UTC)
    assert audit_archive.cutoff(now, years=7).startswith("2023-01-03")  # 7 * 365 days back


def test_archive_needs_a_directory_and_keeps_the_live_trail(monkeypatch, tmp_path):
    t = c.post("/admin/tenants", json={"name": "arch1"}, headers=ADMIN).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=h, json={"name": "Arch"})
    monkeypatch.delenv("AUDIT_ARCHIVE_DIR", raising=False)
    assert c.post("/audit/archive", headers=h).status_code == 409
    monkeypatch.setenv("AUDIT_ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_RETENTION_YEARS", "1")
    # Nothing is older than the window yet, so nothing is archived and the trail is untouched.
    before = c.get("/audit", params={"limit": 500}, headers=h).json()["items"]
    r = c.post("/audit/archive", headers=h)
    assert r.status_code == 200 and r.json()["archived"] == 0
    assert c.get("/audit", params={"limit": 500}, headers=h).json()["items"][0]["id"] >= before[0]["id"]


def test_archive_file_holds_rows_and_an_anchor(monkeypatch, tmp_path):
    t = c.post("/admin/tenants", json={"name": "arch2"}, headers=ADMIN).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=h, json={"name": "Old"})
    from app.audit import AuditEvent
    from app.main import SessionLocal
    from app.rls import bind_tenant
    with SessionLocal() as s:
        bind_tenant(s, t["tenant_id"])
        rows = s.query(AuditEvent).filter_by(tenant_id=t["tenant_id"]).all()
        for r in rows:
            r.ts = "2001-01-01T00:00:00+00:00"  # force them outside any window
        s.commit()
        last_hash = max(rows, key=lambda r: r.id).hash
        result = audit_archive.archive(s, t["tenant_id"], tmp_path, years=7)
        live = s.query(AuditEvent).filter_by(tenant_id=t["tenant_id"]).count()
    assert result["archived"] == len(rows) and live == len(rows)  # copied, not deleted
    lines = [json.loads(x) for x in Path(result["file"]).read_text().splitlines()]
    assert lines[-1]["anchor"] is True and lines[-1]["count"] == len(rows)
    assert lines[-1]["last_hash"] == last_hash
    assert all("prev_hash" in x and "hash" in x for x in lines[:-1])


def test_read_dedupe_is_off_by_default_and_collapses_when_on(monkeypatch):
    t = c.post("/admin/tenants", json={"name": "dedupe"}, headers=ADMIN).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    import io

    from openpyxl import Workbook
    buf = io.BytesIO()
    wb = Workbook()
    wb.active["A1"] = "Revenue"
    wb.save(buf)
    doc_id = c.post("/documents", files={"file": ("d.xlsx", buf.getvalue(), "x")}, data={"deal": "Dd"},
                    headers=h).json()["id"]

    def reads():
        return [r for r in c.get("/audit", params={"action": "document.read"}, headers=h).json()["items"]
                if r["payload"]["doc_id"] == doc_id]

    monkeypatch.delenv("AUDIT_READ_DEDUPE", raising=False)
    c.get(f"/documents/{doc_id}/pages/1", headers=h)
    c.get(f"/documents/{doc_id}/pages/1", headers=h)
    assert len(reads()) == 2
    monkeypatch.setenv("AUDIT_READ_DEDUPE", "1")
    before = len(reads())
    c.get(f"/documents/{doc_id}/pages/1", headers=h)
    c.get(f"/documents/{doc_id}/pages/1", headers=h)
    assert len(reads()) == before  # same person, document and hour: no new line
