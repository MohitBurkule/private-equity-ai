"""Parsing runs in a child process with a time limit. A stuck parse fails its job once, without a retry.
The child is slowed with PARSE_CHILD_DELAY_S (a test hook), so no real file has to hang."""
import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.parse_child import ParseTimeout, parse_in_child
from tests.helpers import new_tenant

c = TestClient(app)


def xlsx_bytes(label):
    wb = Workbook()
    wb.active["A1"] = label
    wb.active["B1"] = 1234
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def wait_for_job(h, job_id, budget=90.0):
    end = time.monotonic() + budget
    while time.monotonic() < end:
        body = c.get(f"/jobs/{job_id}", headers=h).json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.2)
    raise AssertionError("job did not finish in time")


def test_a_parse_in_the_child_returns_the_rows_and_the_parent_stores_them():
    rows = parse_in_child(xlsx_bytes("revenue child"), "model.xlsx", limit=60)
    assert len(rows["documents"]) == 1
    assert rows["documents"][0]["doc"]["kind"] == "xlsx"
    assert any("revenue child" in p["text"] for p in rows["documents"][0]["pages"])


def test_a_parse_past_the_limit_is_killed_and_raises(monkeypatch):
    monkeypatch.setenv("PARSE_CHILD_DELAY_S", "30")
    started = time.monotonic()
    with pytest.raises(ParseTimeout):
        parse_in_child(xlsx_bytes("stuck"), "stuck.xlsx", limit=1.0)
    assert time.monotonic() - started < 25  # killed well before the child's own 30 s sleep ends


def test_a_job_whose_parse_times_out_fails_once_with_a_reason(monkeypatch):
    h = new_tenant(c, "parse-timeout-job")
    monkeypatch.setenv("PARSE_TIMEOUT_S", "1")
    monkeypatch.setenv("PARSE_CHILD_DELAY_S", "30")
    job = c.post("/documents/async", files={"file": ("stuck.xlsx", xlsx_bytes("stuck job"), "x")}, headers=h).json()
    body = wait_for_job(h, job["job_id"])
    assert body["status"] == "failed"
    assert "timed out" in body["error"]
    assert body["attempts"] == 1  # not retried


def test_a_job_within_the_limit_stores_its_document(monkeypatch):
    h = new_tenant(c, "parse-ok-job")
    monkeypatch.delenv("PARSE_CHILD_DELAY_S", raising=False)
    monkeypatch.setenv("PARSE_TIMEOUT_S", "60")
    job = c.post("/documents/async", files={"file": ("ok.xlsx", xlsx_bytes("ok job"), "x")}, headers=h).json()
    body = wait_for_job(h, job["job_id"])
    assert body["status"] == "done", body
    assert len(body["result"]["documents"]) == 1
    docs = c.get("/documents", headers=h).json()
    docs = docs["items"] if isinstance(docs, dict) else docs
    assert [d["filename"] for d in docs] == ["ok.xlsx"]
