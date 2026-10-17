"""OpenTelemetry traces over OTLP/HTTP. Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set and the opentelemetry packages
are installed (the `dev` extra). Then each request is one server span named by its route template, with the request
id and status. Span names, status and request id only: no query strings, headers or bodies are exported, and an
inbound traceparent is honoured so the span joins the caller's trace."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("pe.access")

_tracer = None
_provider = None
_extract = None


def setup() -> bool:
    global _tracer, _provider, _extract
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    try:
        from opentelemetry import propagate
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry is not installed; tracing is off")
        return False
    _provider = TracerProvider(resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "pe-api")}))
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # endpoint read from the environment
    _tracer = _provider.get_tracer("pe.api")
    _extract = propagate.extract
    return True


def start(request, request_id: str):
    if _tracer is None:
        return None
    span = _tracer.start_span(request.method, context=_extract(dict(request.headers)))
    span.set_attribute("pe.request_id", request_id)
    return span


def finish(span, request, status: int) -> None:
    if span is None:
        return
    route = request.scope.get("route")
    path = getattr(route, "path", None) or "unmatched"  # the route template, never the raw URL
    span.update_name(f"{request.method} {path}")
    span.set_attribute("http.request.method", request.method)
    span.set_attribute("http.route", path)
    span.set_attribute("http.response.status_code", status)
    span.end()


def flush() -> None:
    if _provider is not None:
        _provider.force_flush()
