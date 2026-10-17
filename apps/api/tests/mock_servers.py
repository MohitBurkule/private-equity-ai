"""Harness for open-source mock servers (see docs/MOCKS.md). Each mock runs from its jar or binary, so no
Docker is needed; tests skip when the artifact is not configured. Adapters keep their real https URLs, and
`rewrite_http` sends those URLs to the local mock, so adapter code is exercised unchanged."""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WireMock:
    """WireMock standalone (github.com/wiremock/wiremock). Set WIREMOCK_JAR to the jar path to start one per
    test module, or WIREMOCK_URL to use a running server (docker compose service `wiremock`, port 8089)."""

    def __init__(self):
        self.jar = os.environ.get("WIREMOCK_JAR", "")
        self.external = os.environ.get("WIREMOCK_URL", "").rstrip("/")
        self.port = free_port()
        self.base = self.external or f"http://127.0.0.1:{self.port}"
        self.proc = None

    @property
    def available(self) -> bool:
        return bool(self.external) or (bool(self.jar) and Path(self.jar).is_file())

    def __enter__(self):
        if not self.external:
            self.proc = subprocess.Popen(["java", "-jar", self.jar, "--port", str(self.port), "--disable-banner"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{self.base}/__admin/mappings", timeout=1).read()
                if self.external:  # a shared server: start each module from an empty stub set
                    urllib.request.urlopen(urllib.request.Request(f"{self.base}/__admin/mappings/reset", method="POST"),
                                           timeout=5).read()
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("WireMock did not start")

    def __exit__(self, *exc):
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait(timeout=10)

    def stub(self, method: str, request: dict, status: int = 200, body: str | bytes = "", headers: dict | None = None):
        """request: WireMock matcher fields, e.g. {"urlPath": "/v1.0/me/messages"}."""
        resp = {"status": status, "headers": headers or {}}
        if isinstance(body, bytes):
            resp["base64Body"] = base64.b64encode(body).decode()
        else:
            resp["body"] = body
        payload = json.dumps({"request": {"method": method, **request}, "response": resp}).encode()
        req = urllib.request.Request(f"{self.base}/__admin/mappings", data=payload, method="POST",
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()


def rewrite_http(prefixes: dict[str, str]):
    """Injectable Http: maps each real https prefix to a mock base URL, then fetches with urllib.
    Unmapped URLs fail, so a test cannot reach the internet by accident."""

    def http(url: str, headers: dict[str, str]) -> bytes:
        for real, mock in prefixes.items():
            if url.startswith(real):
                target = mock + url[len(real):]
                break
        else:
            raise ValueError(f"no mock for {url.split('?')[0]}")
        body = headers.get("X-Post-Body")
        method = headers.get("X-Method")
        hdrs = {k: v for k, v in headers.items() if k not in ("X-Post-Body", "X-Method")}
        req = urllib.request.Request(target, headers=hdrs, method=method,
                                     data=body.encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    return http
