"""Request ids and a one-line access log. No query strings, headers or bodies are logged."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid

log = logging.getLogger("pe.access")
log.setLevel(logging.INFO)
if not log.handlers:  # uvicorn leaves app loggers unconfigured
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id(inbound: str | None) -> str:
    return inbound if inbound and _OK.match(inbound) else uuid.uuid4().hex


_lock = threading.Lock()
_count: dict[tuple[str, str, str], int] = {}
_ms: dict[tuple[str, str], float] = {}


def _record(request, status: int, ms: float) -> None:
    route = request.scope.get("route")
    path = getattr(route, "path", None) or "unmatched"  # the route template, never the raw URL
    with _lock:
        k = (request.method, path, f"{status // 100}xx")
        _count[k] = _count.get(k, 0) + 1
        _ms[(request.method, path)] = _ms.get((request.method, path), 0.0) + ms


def render_metrics() -> str:
    lines = ["# TYPE pe_requests_total counter"]
    with _lock:
        for (m, p, c), n in sorted(_count.items()):
            lines.append(f'pe_requests_total{{method="{m}",route="{p}",status="{c}"}} {n}')
        lines.append("# TYPE pe_request_ms_sum counter")
        for (m, p), v in sorted(_ms.items()):
            lines.append(f'pe_request_ms_sum{{method="{m}",route="{p}"}} {v:.1f}')
    return "\n".join(lines) + "\n"


async def tracing_middleware(request, call_next):
    rid = request_id(request.headers.get("x-request-id"))
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        _record(request, status, ms)
        log.info(json.dumps({"request_id": rid, "method": request.method, "path": request.url.path,
                             "status": status, "ms": ms}))
