import io
import time

from docx import Document as Docx
from fastapi.testclient import TestClient

from app import jobs
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def docx_bytes(t="hello revenue 1,234"):
    d = Docx()
    d.add_paragraph(t)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def submit(h, data=None, name="a.docx", **form):
    r = c.post("/documents/async", files={"file": (name, data or docx_bytes(), "x")}, data=form, headers=h)
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def wait(h, jid, want=("done", "failed"), timeout=90):  # a cold child parse can take 20 s+ under load
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/jobs/{jid}", headers=h).json()
        if j["status"] in want:
            return j
        time.sleep(0.05)
    raise AssertionError(j)


def test_async_upload_completes_and_document_is_searchable():
    h = new_tenant(c, "jb1")
    j = wait(h, submit(h, docx_bytes("zebra pelts revenue 9,876")))
    assert j["status"] == "done" and j["result"]["documents"][0]["kind"] == "docx"
    assert c.get("/search", params={"q": "zebra pelts"}, headers=h).json()
    assert c.get("/audit/verify", headers=h).json()["ok"] is True
    assert len(c.get("/jobs", headers=h).json()) == 1


def test_parse_failure_is_reported_in_result_not_lost():
    h = new_tenant(c, "jb2")
    j = wait(h, submit(h, b"PK\x03\x04garbage", "bad.zip"))
    assert j["status"] == "done" and j["result"]["documents"] == [] and j["result"]["skipped"]


def test_unexpected_errors_retry_then_fail(monkeypatch):
    h = new_tenant(c, "jb3")
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(jobs, "store_parsed", boom)  # the parent-side write is what retries; the parse runs in a child
    j = wait(h, submit(h))
    assert j["status"] == "failed" and j["attempts"] == jobs.MAX_ATTEMPTS and len(calls) == 3
    assert "db hiccup" in j["error"]


def test_transient_error_then_success(monkeypatch):
    h = new_tenant(c, "jb4")
    real, n = jobs.store_parsed, []

    def flaky(db, tenant, parsed):
        names = [d["doc"]["filename"] for d in parsed["documents"]]
        if names == ["transient.docx"]:  # only this test's job; never another job's call
            n.append(1)
            if len(n) == 1:
                raise RuntimeError("once")
        return real(db, tenant, parsed)
    monkeypatch.setattr(jobs, "store_parsed", flaky)
    j = wait(h, submit(h, name="transient.docx"))
    assert j["status"] == "done" and j["attempts"] == 2


def test_scan_failure_fails_job_and_nothing_is_stored(monkeypatch):
    h = new_tenant(c, "jb5")
    monkeypatch.setenv("SCAN_COMMAND", "false")
    j = wait(h, submit(h))
    assert j["status"] == "failed" and "malware scan failed" in j["error"]
    assert c.get("/documents", headers=h).json() == []
    monkeypatch.setenv("SCAN_COMMAND", "true")
    assert wait(h, submit(h))["status"] == "done"


def test_walls_apply_in_background_and_jobs_are_private():
    t = c.post("/admin/tenants", json={"name": "jb6"}, headers=ADMIN).json()
    owner = {"Authorization": f"Bearer {t['api_key']}"}
    k = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"deals": ["alpha"]}, headers=ADMIN).json()
    walled = {"Authorization": f"Bearer {k['api_key']}"}
    r = c.post("/documents/async", files={"file": ("a.docx", docx_bytes(), "x")}, headers=walled)
    assert r.status_code == 403  # deal required for a walled key
    jid = submit(walled, deal="alpha")
    j = wait(walled, jid)
    assert j["status"] == "done"
    docs = c.get("/documents", headers=owner).json()
    assert [d["deal"] for d in docs] == ["alpha"]
    other = new_tenant(c, "jb7")
    assert c.get(f"/jobs/{jid}", headers=other).status_code == 404
    assert c.get(f"/jobs/{jid}", headers=owner).status_code == 200
    viewer = {"Authorization": "Bearer " + c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "viewer"},
                                                    headers=ADMIN).json()["api_key"]}
    assert c.post("/documents/async", files={"file": ("a.docx", docx_bytes(), "x")}, headers=viewer).status_code == 403


def test_requeue_endpoint_needs_admin():
    assert c.post("/admin/jobs/requeue").status_code == 403
    assert c.post("/admin/jobs/requeue", headers=ADMIN).status_code == 200
