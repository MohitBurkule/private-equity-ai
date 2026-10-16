"""SEC EDGAR client for companyfacts. SEC requires a descriptive User-Agent and <=10 req/s.

The HTTP getter is injectable so tests (and air-gapped deployments feeding cached JSON) never
touch the network. Set SEC_USER_AGENT to "Company name contact@example.com".
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable

Getter = Callable[[str], bytes]
_lock = threading.Lock()
_last = 0.0


def _default_get(url: str) -> bytes:
    global _last
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("SEC_USER_AGENT is not set (SEC requires a contact in the User-Agent)")
    with _lock:  # crude 8 req/s limiter, shared across threads
        wait = 0.125 - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_companyfacts(cik: int | str, get: Getter | None = None) -> dict:
    cik10 = str(int(cik)).zfill(10)
    raw = (get or _default_get)(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
    return json.loads(raw)
