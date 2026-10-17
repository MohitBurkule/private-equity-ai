#!/usr/bin/env python3
"""Parity replay for the Rust API against FastAPI (run by scripts/parity.sh, not by make ci).

Seeds one tenant through FastAPI, then replays the same GET requests against both stacks, one key at a time.
Each request is diffed on status, body (key order ignored) and the audit rows it wrote (actor, action, payload).
Write routes are not replayed: the Rust API relays them to FastAPI, so they match by construction.
Exits 1 on any difference."""

import json
import os
import sys
import urllib.error
import urllib.request

import psycopg

FA = os.environ["PARITY_FASTAPI"]
RS = os.environ["PARITY_RUST"]
ADMIN_TOKEN = os.environ["PARITY_ADMIN_TOKEN"]
DSN = os.environ["PARITY_DB_URL"]


def call(base, path, key=None, method="GET", body=None, headers=None):
    h = dict(headers or {})
    if key:
        h["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")


def seed():
    """Keys and rows go in through FastAPI's own routes, so the seed is the same for both sides."""
    keys = {}
    admin_hdr = {"X-Admin-Token": ADMIN_TOKEN}
    status, out = call(FA, "/admin/tenants", method="POST", body={"name": "parity"}, headers=admin_hdr)
    assert status == 201, out
    keys["admin"] = out["api_key"]
    tenant_id = out["tenant_id"]
    for name, body in [
        ("scoped_other", {"role": "analyst", "deals": ["Other"]}),
        ("zeta", {"role": "analyst", "deals": ["Zeta"]}),
        ("analyst", {"role": "analyst"}),
    ]:
        status, out = call(FA, f"/admin/tenants/{tenant_id}/keys", method="POST", body=body, headers=admin_hdr)
        assert status == 201, out
        keys[name] = out["api_key"]
    a = keys["admin"]
    for body in [{"name": "Other"}, {"name": "Zeta", "mnpi": True}]:
        status, out = call(FA, "/deals", a, "POST", body)
        assert status == 201, out
    for deal in ["Other", "Zeta"]:
        status, _ = call(FA, f"/deals/{deal}/notes", a, "POST", {"body": f"{deal} note"})
        assert status == 201
        status, _ = call(FA, f"/deals/{deal}/checklist", a, "POST", {"title": f"{deal} step"})
        assert status == 201
    return keys


def audit_marker(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(id), 0) FROM audit_event")
        return cur.fetchone()[0]


def audit_since(conn, marker):
    """Audit rows written after `marker`. Ids and timestamps differ between stacks, so only actor, action and payload compare."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor, action, payload FROM audit_event WHERE id > %s ORDER BY id", (marker,)
        )
        return cur.fetchall()


def main():
    with psycopg.connect(DSN, autocommit=True) as conn:
        keys = seed()
        requests = [
            ("/health", None),
            ("/memo/templates", None),
        ]
        for name in keys:
            for path in [
                "/deals",
                "/deals/Other/notes",
                "/deals/Zeta/notes",
                "/deals/Nope/notes",
                "/deals/Other/checklist",
                "/deals/Zeta/checklist",
                "/deals/Other/snapshot",
                "/deals/Zeta/snapshot",
                "/documents",
                "/memo/versions?entity=Other",
                "/memo/versions/1",
            ]:
                requests.append((path, name))
        failures = 0
        for path, who in requests:
            key = keys.get(who) if who else None
            results = {}
            for label, base in [("fastapi", FA), ("rust", RS)]:
                marker = audit_marker(conn)
                status, body = call(base, path, key)
                results[label] = (status, body, audit_since(conn, marker))
            fa, rs = results["fastapi"], results["rust"]
            same = fa[0] == rs[0] and fa[1] == rs[1] and fa[2] == rs[2]
            label = f"{who or 'anon'} {path}"
            print(f"{'SAME' if same else 'DIFF'} {label} status={fa[0]}/{rs[0]} audit={len(fa[2])}/{len(rs[2])}")
            if not same:
                failures += 1
                print("  fastapi:", fa)
                print("  rust:   ", rs)
    print("PARITY OK" if failures == 0 else f"PARITY FAILED: {failures} request(s) differ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
