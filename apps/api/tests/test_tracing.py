import json
import logging

from fastapi.testclient import TestClient

from app.main import app
from app.tracing import request_id

c = TestClient(app)


def test_id_generated_echoed_and_sanitised():
    r = c.get("/health")
    assert len(r.headers["x-request-id"]) == 32
    assert c.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    assert request_id("bad id\nwith newline") != "bad id\nwith newline"
    assert request_id("x" * 65) != "x" * 65


def test_access_log_has_no_query_string(caplog):
    with caplog.at_level(logging.INFO, logger="pe.access"):
        c.get("/health?secret=1", headers={"X-Request-ID": "r1"})
    rec = json.loads(caplog.records[-1].message)
    assert rec["request_id"] == "r1" and rec["path"] == "/health" and "secret" not in caplog.text


def test_metrics_need_admin_and_use_route_templates_not_raw_urls():
    from tests.helpers import new_tenant
    h = new_tenant(c, "mt1")
    c.get("/documents/abc123/pages/1", headers=h)
    assert c.get("/metrics").status_code == 403
    body = c.get("/metrics", headers={"X-Admin-Token": "test-admin"}).text
    assert 'route="/documents/{doc_id}/pages/{number}"' in body and "abc123" not in body
    assert 'status="2xx"' in body and "pe_request_ms_sum" in body
