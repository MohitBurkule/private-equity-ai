"""OTLP traces: each request becomes one span with its route template, joined to the caller's trace. Exported to a
local OTLP/HTTP receiver (a stand-in for an OpenTelemetry collector; no Docker here), decoded from protobuf."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from app import otel
from app.main import app

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = "00f067aa0ba902b7"


class Receiver(BaseHTTPRequestHandler):
    bodies: ClassVar[list[bytes]] = []

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        Receiver.bodies.append(self.rfile.read(n))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture()
def collector(monkeypatch):
    Receiver.bodies = []
    srv = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{srv.server_port}")
    for name in ("_tracer", "_provider", "_extract"):
        monkeypatch.setattr(otel, name, None)
    assert otel.setup() is True
    yield Receiver
    otel.flush()
    srv.shutdown()


def exported_spans(collector):
    spans = []
    for body in collector.bodies:
        for rs in ExportTraceServiceRequest.FromString(body).resource_spans:
            for ss in rs.scope_spans:
                spans.extend(ss.spans)
    return spans


def attrs(span):
    return {kv.key: (kv.value.string_value or kv.value.int_value) for kv in span.attributes}


def test_request_span_uses_route_template_and_joins_callers_trace(collector):
    r = TestClient(app).get("/health", headers={"traceparent": f"00-{TRACE}-{PARENT}-01"})
    assert r.status_code == 200
    otel.flush()
    (span,) = [s for s in exported_spans(collector) if s.name == "GET /health"]
    assert span.trace_id.hex() == TRACE and span.parent_span_id.hex() == PARENT
    assert attrs(span)["http.route"] == "/health" and attrs(span)["http.response.status_code"] == 200
    assert attrs(span)["pe.request_id"] == r.headers["X-Request-ID"]


def test_query_string_and_headers_are_not_exported(collector):
    TestClient(app).get("/health?token=s3cret-value", headers={"Authorization": "Bearer pe_hidden"})
    otel.flush()
    raw = b"".join(collector.bodies)
    assert b"s3cret-value" not in raw and b"pe_hidden" not in raw


def test_no_endpoint_means_no_tracing(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(otel, "_tracer", None)
    assert otel.setup() is False
    assert otel.start(None, "x") is None
