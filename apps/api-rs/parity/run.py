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


def seed(conn):
    """Keys and deal rows go in through FastAPI's own routes. Alerts come from the watchers, so they are inserted
    directly, with the same rows for both stacks to read."""
    keys = {}
    admin_hdr = {"X-Admin-Token": ADMIN_TOKEN}
    status, out = call(FA, "/admin/tenants", method="POST", body={"name": "parity"}, headers=admin_hdr)
    assert status == 201, out
    keys["admin"] = out["api_key"]
    tenant_id = out["tenant_id"]
    with conn.cursor() as cur:
        for kind, severity, title, created in [
            ("sec_filings", "info", "New 10-Q", "2026-10-15T08:00:00+00:00"),
            ("covenant", "critical", "Leverage covenant breach", "2026-10-16T08:00:00+00:00"),
            ("sec_filings", "warning", "Late filing", "2026-10-17T08:00:00+00:00"),
            ("covenant", "critical", "Liquidity below floor", "2026-10-17T09:00:00+00:00"),
        ]:
            cur.execute(
                "INSERT INTO alert (tenant_id, kind, severity, title, detail, dedupe_key, fact_ids, status, created_at)"
                " VALUES (%s, %s, %s, %s, 'detail', %s, '[1]', 'new', %s)",
                (tenant_id, kind, severity, title, f"{kind}:{title}", created),
            )
        for deal, category, title, status in [
            ("Other", "Financials", "Audited FY24", "open"),
            ("Other", "Financials", "Tax returns", "received"),
            ("Other", "Legal", "Charter", "waived"),
            ("Zeta", "Legal", "Shareholder agreement", "open"),
        ]:
            cur.execute(
                "INSERT INTO dd_request (tenant_id, deal, category, title, status, note, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, '', '2026-10-17T10:00:00+00:00')",
                (tenant_id, deal, category, title, status),
            )
        cur.execute(
            "INSERT INTO dd_question (tenant_id, deal, question, status, asked_at)"
            " VALUES (%s, 'Other', 'Any pending litigation?', 'open', '2026-10-17T10:00:00+00:00')",
            (tenant_id,),
        )
        cur.execute(
            "INSERT INTO dd_question (tenant_id, deal, question, status, answer, asked_at, answered_at)"
            " VALUES (%s, 'Zeta', 'Who signs?', 'answered', 'The CFO', '2026-10-17T10:00:00+00:00',"
            " '2026-10-17T11:00:00+00:00')",
            (tenant_id,),
        )
        cur.execute(
            "INSERT INTO peer_set (tenant_id, deal, name, target_id, items, dropped, refreshed_at, created_by, created_at)"
            " VALUES (%s, 'Other', 'Software peers', 1, %s, '[]', '2026-10-17T12:00:00+00:00', 'seed', '2026-10-17T12:00:00+00:00')",
            (tenant_id, '[{"cik": "1", "name": "Peer A", "revenue": "100", "period": "FY24", "source_url": "https://example.test/a"}]'),
        )
        cur.execute(
            "INSERT INTO document (id, tenant_id, sha256, filename, n_pages, kind, deal, created_at)"
            " VALUES (%s, %s, %s, 'other-10k.pdf', 3, 'pdf', 'Other', '2026-10-17T10:00:00+00:00')",
            ("d" * 64, tenant_id, "b" * 64),
        )
        cur.execute(
            "INSERT INTO document (id, tenant_id, sha256, filename, n_pages, kind, deal, created_at)"
            " VALUES (%s, %s, %s, 'zeta-cim.pdf', 3, 'pdf', 'Zeta', '2026-10-17T10:00:00+00:00')",
            ("e" * 64, tenant_id, "c" * 64),
        )
        for entity, doc, metric, period, value in [
            ("Other", "d" * 64, "revenue", "FY23", 100),
            ("Other", "d" * 64, "revenue", "FY24", 120),
            ("Other", "d" * 64, "gross_profit", "FY24", 60),
            ("Other", "d" * 64, "net_income", "FY24", -5),
            ("Other", "d" * 64, "operating_cash_flow", "FY24", 30),
            ("Other", "d" * 64, "capex", "FY24", -10),
            ("Other", "d" * 64, "long_term_debt", "FY24", 50),
            ("Other", "d" * 64, "cash", "FY24", 20),
            ("Other", "d" * 64, "operating_income", "FY24", 15),
            ("Other", "d" * 64, "depreciation_and_amortization", "FY24", 5),
            ("Zeta", "e" * 64, "revenue", "FY24", 500),
            ("PeerA", "d" * 64, "enterprise_value", "FY24", 1200),
            ("PeerA", "d" * 64, "revenue", "FY24", 240),
            ("PeerB", "d" * 64, "enterprise_value", "FY24", 900),
            ("PeerB", "d" * 64, "revenue", "FY24", 300),
            ("PeerC", "d" * 64, "enterprise_value", "FY24", 700),
            ("Zeta", "e" * 64, "enterprise_value", "FY24", 2000),
        ]:
            cur.execute(
                "INSERT INTO fact (tenant_id, entity, metric, period, value, unit, basis, status)"
                " VALUES (%s, %s, %s, %s, %s, 'USD', 'GAAP', 'verified') RETURNING id",
                (tenant_id, entity, metric, period, value),
            )
            fact_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO fact_source (fact_id, document_id, page, quote, kind)"
                " VALUES (%s, %s, 1, %s, 'pdf')",
                (fact_id, doc, f"{metric} {period} {value}"),
            )
        cur.execute(
            "INSERT INTO firm_knowledge (tenant_id, key, value, document_id, page, quote, status)"
            " VALUES (%s, 'lp_reporting_tone', 'formal and plain', %s, 2, 'Formal and plain.', 'accepted')",
            (tenant_id, "d" * 64),
        )
        cur.execute(
            "INSERT INTO firm_knowledge (tenant_id, key, value, document_id, page, quote, status)"
            " VALUES (%s, 'board_meeting_frequency', 'monthly', %s, 1, 'Board meets monthly.', 'accepted')",
            (tenant_id, "e" * 64),
        )
        for doc_id, filename, deal, sha, text in [
            ("f" * 64, "nda-other.pdf", "Other", "d" * 64,
             "Mutual Non-Disclosure Agreement between the parties. This Agreement shall be governed by the laws of "
             "the State of Delaware. The obligations of confidentiality survive for seven (7) years. Each party will "
             "not solicit employees for a period of four (4) years."),
            ("g" * 64, "board-minutes-zeta.pdf", "Zeta", "e" * 64, "Board minutes for the Zeta deal team."),
            ("h" * 64, "minutes-other.pdf", "Other", "f" * 64, "Minutes of the operating committee."),
        ]:
            cur.execute(
                "INSERT INTO document (id, tenant_id, sha256, filename, n_pages, kind, deal, created_at)"
                " VALUES (%s, %s, %s, %s, 1, 'pdf', %s, '2026-10-17T10:00:00+00:00')",
                (doc_id, tenant_id, sha, filename, deal),
            )
            cur.execute(
                "INSERT INTO page (document_id, number, text) VALUES (%s, 1, %s)",
                (doc_id, text),
            )
        cur.execute(
            "INSERT INTO workflow_schedule (id, tenant_id, name, kind, params, every_days, recipients, next_run,"
            " last_run, last_status, last_result, active)"
            " VALUES (9001, %s, 'Weekly report', 'portfolio_report', '{}', 7, '', '2026-10-24T00:00:00+00:00',"
            " '2026-10-17T00:00:00+00:00', 'ok', '{\"sent\": 1}', 1),"
            " (9002, %s, 'Comps refresh', 'comps', '{}', 30, 'a@example.test', '2026-11-16T00:00:00+00:00',"
            " NULL, 'failed', 'peer feed timed out', 0)",
            (tenant_id, tenant_id),
        )
        cur.execute(
            "INSERT INTO memo_template (tenant_id, name, sections, headings, intro, created_by, created_at)"
            " VALUES (%s, 'board', '[\"financial\", \"risks\", \"rules\"]', '{\"financial\": \"Numbers\"}',"
            " 'Draft for the board.', 'seed', '2026-10-17T10:00:00+00:00')",
            (tenant_id,),
        )
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
        keys = seed(conn)
        requests = [
            ("/health", None),
            ("/memo/templates", None),
        ]
        for name in ["admin", "scoped_other", "zeta", "analyst"]:
            for path in ["/alerts/brief", "/dd/summary", "/dd/requests", "/dd/requests?deal=Other", "/dd/requests?status=open",
                         "/dd/questions", "/dd/questions?deal=Zeta", "/dd/summary?deal=Other",
                         "/dd/summary?deal=Zeta", "/dd/summary?deal=Nope"]:
                requests.append((path, name))
            for path in ["/alerts", "/alerts?status=new", "/alerts/brief?since=2026-10-16T00:00:00%2B00:00",
                         "/alerts/brief?since=2030-01-01T00:00:00%2B00:00"]:
                requests.append((path, name))
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
                "/deals/Other/peer-sets",
                "/deals/Zeta/peer-sets",
                "/deals/Nope/peer-sets",
                "/memo?entity=Other",
                "/memo?entity=Zeta",
                "/memo?entity=Nope",
                "/memo",
                "/memo?entity=Other&peers=A,B&period=FY24",
                "/memo?entity=Other&peers=PeerA,PeerB,Zeta,PeerC&period=FY24",
                "/memo?entity=Zeta&peers=Other,PeerA,PeerB&period=FY24",
                "/memo?entity=Other&peers=PeerA,PeerB,PeerC&period=FY23",
                "/memo?entity=Other&legal_doc=" + "f" * 64,
                "/memo?entity=Other&legal_doc=" + "g" * 64,
                "/memo?entity=Other&legal_doc=" + "h" * 64,
                "/memo?entity=Other&legal_doc=" + "x" * 64,
                "/memo/sections?entity=Other",
                "/memo/sections?entity=Zeta&template=snapshot",
                "/memo/sections?entity=Other&template=board",
                "/memo/sections?entity=Other&template=nope",
                "/memo/sections?entity=Nope",
                "/memo/sections",
                "/workflows",
                "/workflows/9001/last",
                "/workflows/9002/last",
                "/workflows/9999/last",
                "/workflows/abc/last",
                "/facts/derived?formula=ebitda&entity=Other&period=FY24",
                "/facts/derived?formula=ebitda&entity=Other&period=FY23",
                "/facts/derived?formula=ebitda&entity=Zeta&period=FY24",
                "/facts/derived?formula=nope&entity=Other&period=FY24",
                "/facts/derived",
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
