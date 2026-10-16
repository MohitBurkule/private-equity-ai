"""Request ids and a one-line access log. No query strings, headers or bodies are logged."""
from __future__ import annotations

import json
import logging
import re
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
        log.info(json.dumps({"request_id": rid, "method": request.method, "path": request.url.path,
                             "status": status, "ms": round((time.perf_counter() - t0) * 1000, 1)}))
