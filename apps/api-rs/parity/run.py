#!/usr/bin/env python3
"""Parity replay for the Rust API against FastAPI (run by scripts/parity.sh, not by make ci).

Seeds one tenant through FastAPI, then replays the same GET requests against both stacks, one key at a time.
Each request is diffed on status, body (key order ignored) and the audit rows it wrote (actor, action, payload).
Write routes are not replayed: the Rust API relays them to FastAPI, so they match by construction.
Exits 1 on any difference."""

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

import psycopg

FA = os.environ["PARITY_FASTAPI"]
RS = os.environ["PARITY_RUST"]
ADMIN_TOKEN = os.environ["PARITY_ADMIN_TOKEN"]
TENANT_ID = None
REVOKE_KID = None
ADMIN_KID = None
GRAPH_KID = None
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
    global ADMIN_KID
    ADMIN_KID = hashlib.sha256(out["api_key"].encode()).hexdigest()[:12]
    tenant_id = out["tenant_id"]
    global TENANT_ID
    TENANT_ID = tenant_id
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
        for deal, ext, title, starts_at, url, board in [
            ("Other", "parity-1", "Board meeting: Other", "2024-02-01", "https://cal.example.test/1", True),
            ("Other", "parity-2", "Diligence call: Other", "2024-01-10", "", False),
            ("Zeta", "parity-3", "Zeta intro call", "2024-03-01", "https://cal.example.test/3", False),
        ]:
            cur.execute(
                "INSERT INTO calendar_event (tenant_id, source, external_id, title, starts_at, url, board, deal)"
                " VALUES (%s, 'parity', %s, %s, %s, %s, %s, %s)",
                (tenant_id, ext, title, starts_at, url, board, deal),
            )
        for company, round_date, round_type, post_money, ccy, doc, line in [
            ("Other", "2023-06-01", "Seed", "250", "EUR", "d" * 64, 1),
            ("Other", "2024-01-15", "Series B", "1000", "USD", "d" * 64, 2),
            ("Zeta", "2024-03-01", "Series C", "2500.5", "USD", "e" * 64, 3),
        ]:
            cur.execute(
                "INSERT INTO valuation_round (tenant_id, company, round_date, round_type, post_money, currency,"
                " document_id, line) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (tenant_id, company, round_date, round_type, post_money, ccy, doc, line),
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
            ("Other", "d" * 64, "revenue", "FY23", "100.5"),
            ("Other", "d" * 64, "capex", "FY22", 0),
            ("Other", "d" * 64, "revenue", "Q1-24", 30),
            ("Other", "d" * 64, "revenue", "Q1-23", 25),
            ("Other", "d" * 64, "total_debt", "FY24", 60),
            ("Other", "d" * 64, "lease_liabilities", "FY24", 5),
            ("Other", "d" * 64, "pension_deficit", "FY24", 8),
            ("Levered", "d" * 64, "revenue", "FY23", "100.5"),
            ("Levered", "d" * 64, "revenue", "Q1-24", 30),
            ("Levered", "d" * 64, "revenue", "Q1-23", 25),
            ("Levered", "d" * 64, "total_debt", "FY24", 60),
            ("Levered", "d" * 64, "lease_liabilities", "FY24", 5),
            ("Levered", "d" * 64, "pension_deficit", "FY24", 8),
            ("Levered", "d" * 64, "current_assets", "FY24", "40.25"),
            ("Levered", "d" * 64, "cash", "FY24", 20),
            ("Levered", "d" * 64, "current_liabilities", "FY24", 25),
            ("Levered", "d" * 64, "short_term_debt", "FY24", 5),
            ("Levered", "d" * 64, "current_assets", "FY23", 30),
            ("Levered", "d" * 64, "cash", "FY23", 10),
            ("Levered", "d" * 64, "current_liabilities", "FY23", 18),
            ("Levered", "d" * 64, "short_term_debt", "FY23", 0),
            ("Levered", "d" * 64, "revenue", "FY23", 200),
            ("Levered", "d" * 64, "revenue", "FY24", 230),
            ("Levered", "d" * 64, "ebitda_bridge reported", "FY24", 50),
            ("Levered", "d" * 64, "ebitda_bridge add_back", "FY24", 8),
            ("Levered", "d" * 64, "ebitda_bridge deduction", "FY24", 3),
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
        # An unreviewed bridge line: normalized EBITDA is withheld until a person reviews it.
        cur.execute(
            "INSERT INTO fact (tenant_id, entity, metric, period, value, unit, basis, status)"
            " VALUES (%s, 'Levered', 'ebitda_bridge reported', 'FY23', 180, 'USD', 'GAAP', 'auto') RETURNING id",
            (tenant_id,),
        )
        cur.execute(
            "INSERT INTO fact_source (fact_id, document_id, page, quote, kind)"
            " VALUES (%s, %s, 1, 'ebitda_bridge reported FY23 180', 'pdf')",
            (cur.fetchone()[0], "d" * 64),
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
            "INSERT INTO document_source (tenant_id, document_id, connector, external_id, version, url, acl)"
            " VALUES (%s, %s, 'sharepoint', 'sp-1', 'v1', 'https://example.test/nda', '[\"alice\"]')",
            (tenant_id, "f" * 64),
        )
        cur.execute(
            "INSERT INTO agent_run (id, tenant_id, kind, name, goal, status, steps, result, error, created_at)"
            " VALUES (8001, %s, 'workflow', 'build_firm_profile', NULL, 'done',"
            " '[{\"id\": \"extract\", \"tool\": \"extract_firm_knowledge\"}]', '{\"rules\": 2}', NULL,"
            " '2026-10-17T09:00:00+00:00'),"
            " (8002, %s, 'agent', 'agent', 'find the EBITDA', 'failed', '[]', NULL, 'step budget exhausted',"
            " '2026-10-17T10:00:00+00:00')",
            (tenant_id, tenant_id),
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
    status, out = call(FA, f"/admin/tenants/{tenant_id}/keys", method="POST",
                       body={"role": "analyst", "deals": None}, headers=admin_hdr)
    assert status == 201, out
    global REVOKE_KID
    REVOKE_KID = hashlib.sha256(out["api_key"].encode()).hexdigest()[:12]
    status, out = call(FA, f"/admin/tenants/{tenant_id}/keys", method="POST",
                       body={"role": "analyst", "identity": "Ana@Example.test"}, headers=admin_hdr)
    assert status == 201, out
    global GRAPH_KID
    GRAPH_KID = hashlib.sha256(out["api_key"].encode()).hexdigest()[:12]
    a = keys["admin"]
    for body in [{"name": "Other"}, {"name": "Zeta", "mnpi": True}]:
        status, out = call(FA, "/deals", a, "POST", body)
        assert status == 201, out
    # Saved connections go in directly: the token is sealed by FastAPI, and this list never reads it.
    with conn.cursor() as cur:
        for connector, deal in [("gmail", "Other"), ("mailpit", "Zeta")]:
            cur.execute(
                "INSERT INTO connection (tenant_id, connector, deal, options, token_sealed, interval_minutes,"
                " last_run, last_status, created_by) VALUES (%s, %s, %s, '{}', 'parity', NULL, NULL, NULL, 'parity')",
                (TENANT_ID, connector, deal),
            )
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


def normalize_generated(method, path, body):
    """Keys and tenant ids are random, so the two stacks issue different values. Only those are masked."""
    if method == "POST" and (path == "/admin/tenants" or path.endswith("/keys")) and isinstance(body, dict):
        return {k: ("<generated>" if k in ("api_key", "key_id", "tenant_id") else v) for k, v in body.items()}
    return body


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
            ("/agent/tools", "admin"),
            ("/agent/tools", "analyst"),
            ("/agent/tools", None),
            ("/agent/workflows", "admin"),
            ("/agent/workflows", "zeta"),
            ("/compliance/access-report?deal=Atlas", "admin"),
            ("/compliance/access-report?deal=Atlas", "analyst"),
            ("/compliance/access-report?deal=Atlas", "scoped_other"),
            ("/compliance/access-report?deal=Atlas&limit=1", "admin"),
            ("/compliance/access-report?deal=Atlas&limit=0", "admin"),
            ("/compliance/access-report?deal=Atlas&limit=5001", "admin"),
            ("/compliance/access-report", "admin"),
            ("/connectors", "admin"),
            ("/connectors", "analyst"),
            ("/connectors", "zeta"),
            ("/connections", "admin"),
            ("/connections", "scoped_other"),
            ("/connections", "zeta"),
            ("/connections", None),
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
                "/valuation-rounds",
                "/deals/Other/meetings",
                "/deals/Zeta/meetings",
                "/deals/Nope/meetings",
                "/valuation-rounds?company=Other",
                "/valuation-rounds?company=Nope",
                "/audit",
                "/audit/verify",
                "/agent/runs",
                "/agent/runs?limit=1",
                "/agent/runs?limit=0",
                "/agent/runs?limit=500",
                "/agent/runs?limit=abc",
                "/calc/periods?entity=Other",
                "/calc/periods?entity=Zeta",
                "/calc/periods?entity=Nope",
                "/calc/periods",
                "/audit?action=document.read",
                "/audit?limit=2",
                "/audit?limit=500",
                "/audit?action=",
                "/audit?limit=0",
                "/audit?limit=501",
                "/audit?limit=abc",
                "/audit?limit=",
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
                "/facts?entity=Other",
                "/calc/ltm?entity=Levered&metric=revenue&fy=FY24&ytd=Q1-24&ytd_prior=Q1-23",
                "/calc/ltm?entity=Levered&metric=revenue&fy=FY23&ytd=Q1-24&ytd_prior=Q1-23",
                "/calc/ltm?entity=Levered&metric=revenue&fy=FY24&ytd=Nope&ytd_prior=Q1-23",
                "/calc/ltm?entity=Levered&metric=net_income&fy=FY24&ytd=Q1-24&ytd_prior=Q1-23",
                "/calc/ltm?entity=Zeta&metric=revenue&fy=FY24&ytd=Q1-24&ytd_prior=Q1-23",
                "/calc/ltm?entity=Levered&metric=revenue&fy=FY24&ytd=Q1-24",
                "/calc/ltm",
                "/calc/net-debt?entity=Levered&period=FY24",
                "/calc/net-debt?entity=Levered&period=FY24&include_leases=false",
                "/calc/net-debt?entity=Levered&period=FY24&include_leases=maybe",
                "/calc/net-debt?entity=Levered&period=FY23",
                "/calc/net-debt?entity=Zeta&period=FY24",
                "/calc/net-debt",
                "/calc/nwc?entity=Levered&period=FY24",
                "/calc/nwc?entity=Levered&period=FY23",
                "/calc/nwc?entity=Levered&period=FY22",
                "/calc/nwc?entity=Zeta&period=FY24",
                "/calc/nwc",
                "/calc/nwc-peg?entity=Levered&periods=FY23,FY24",
                "/calc/nwc-peg?entity=Levered&periods=FY24",
                "/calc/nwc-peg?entity=Levered&periods=FY23,FY22",
                "/calc/nwc-peg?entity=Levered&periods=",
                "/calc/nwc-peg?entity=Zeta&periods=FY24",
                "/calc/nwc-peg",
                "/calc/revenue-trend?entity=Levered&periods=FY23,FY24",
                "/calc/revenue-trend?entity=Levered&periods=FY22,FY24",
                "/calc/revenue-trend?entity=Zeta&periods=FY24",
                "/calc/revenue-trend?entity=Levered&periods=",
                "/calc/revenue-trend",
                "/calc/normalized-ebitda?entity=Levered&period=FY24",
                "/calc/normalized-ebitda?entity=Levered&period=FY23",
                "/calc/normalized-ebitda?entity=Levered&period=FY22",
                "/calc/normalized-ebitda?entity=Zeta&period=FY24",
                "/calc/normalized-ebitda",
                "POST /calc/sumcheck|{\"parts\": [1, 2, 3], \"stated\": 6}",
                "POST /calc/sumcheck|{\"parts\": [\"1.50\", \"2.25\"], \"stated\": \"3.70\"}",
                "POST /calc/sumcheck|{\"parts\": [1000, 2000], \"stated\": 3002, \"rounding_unit\": 1}",
                "POST /calc/sumcheck|{\"parts\": [1000, 2000], \"stated\": 3010, \"rounding_unit\": 1}",
                "POST /calc/sumcheck|{\"parts\": [], \"stated\": 0}",
                "POST /calc/sumcheck|{\"parts\": [1, 2], \"stated\": 5}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"1\", \"2\"]}, \"base\": [\"0\", \"0\", \"0\"], \"total\": [\"1\", \"2\", \"0\"]}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2023-01-01\", \"amount\": \"-100\"}, {\"date\": \"2024-01-01\", \"amount\": \"-50\"}, {\"date\": \"2025-06-30\", \"amount\": \"80\"}], \"nav\": \"120\", \"as_of\": \"2025-12-31\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2023-01-01\", \"amount\": \"-100\"}, {\"date\": \"2024-07-01\", \"amount\": \"150\"}], \"nav\": \"0\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2023-01-01\", \"amount\": \"10\"}], \"nav\": \"0\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2023-01-01\", \"amount\": \"-100\"}], \"nav\": \"-5\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2026-01-01\", \"amount\": \"-100\"}], \"nav\": \"0\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2023-01-01\", \"amount\": \"10\"}, {\"date\": \"2024-01-01\", \"amount\": \"20.5\"}], \"nav\": \"0\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2023-03-01\", \"amount\": \"-100\"}, {\"date\": \"2023-03-01\", \"amount\": \"50\"}], \"nav\": \"0\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2024-01-01\", \"amount\": \"-100\"}, {\"date\": \"2023-01-01\", \"amount\": \"-100\"}], \"nav\": \"10\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/fund-metrics|{\"flows\": [{\"date\": \"2025-06-30\", \"amount\": \"80\"}, {\"date\": \"2023-01-01\", \"amount\": \"-100.00\"}, {\"date\": \"2024-01-01\", \"amount\": \"-50.5\"}], \"nav\": \"120.25\", \"as_of\": \"2025-12-31\"}",
                "POST /calc/fund-metrics|{\"flows\": [], \"nav\": \"0\", \"as_of\": \"2025-01-01\"}",
                "POST /calc/waterfall|{\"exit_value\": \"1000\", \"common_shares\": \"100\", \"classes\": [{\"name\": \"A\", \"shares\": \"50\", \"invested\": \"300\"}, {\"name\": \"B\", \"shares\": \"30\", \"invested\": \"200\", \"rank\": 2, \"participating\": true, \"cap_multiple\": \"3\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"500\", \"common_shares\": \"0\", \"classes\": [{\"name\": \"A\", \"shares\": \"10\", \"invested\": \"300\"}, {\"name\": \"B\", \"shares\": \"20\", \"invested\": \"300\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"0\", \"common_shares\": \"100\", \"classes\": [{\"name\": \"A\", \"shares\": \"10\", \"invested\": \"300\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"1000\", \"common_shares\": \"100\", \"classes\": [{\"name\": \"A\", \"shares\": \"500\", \"invested\": \"100\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"100\", \"common_shares\": \"2\", \"classes\": [{\"name\": \"P\", \"shares\": \"1\", \"invested\": \"0\", \"participating\": true}]}",
                "POST /calc/waterfall|{\"exit_value\": \"1000\", \"common_shares\": \"10\", \"classes\": [{\"name\": \"P\", \"shares\": \"100\", \"invested\": \"100\", \"participating\": true, \"cap_multiple\": \"2\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"-1\", \"common_shares\": \"10\", \"classes\": []}",
                "POST /calc/waterfall|{\"exit_value\": \"10\", \"common_shares\": \"10\", \"classes\": [{\"name\": \"A\", \"shares\": \"1\", \"invested\": \"1\"}, {\"name\": \"A\", \"shares\": \"1\", \"invested\": \"1\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"10\", \"common_shares\": \"10\", \"classes\": [{\"name\": \"common\", \"shares\": \"1\", \"invested\": \"1\"}]}",
                "POST /calc/waterfall|{\"exit_value\": \"900\", \"common_shares\": \"0\", \"classes\": [{\"name\": \"A\", \"shares\": \"1\", \"invested\": \"100\", \"rank\": 1}, {\"name\": \"B\", \"shares\": \"1\", \"invested\": \"200\", \"rank\": 1}, {\"name\": \"C\", \"shares\": \"5\", \"invested\": \"50\", \"rank\": 2, \"pref_multiple\": \"1.5\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"1000\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"allot\", \"date\": \"2024-01-05\", \"source\": \"SH01 a\", \"allotted\": \"100\", \"total_after\": \"1100\"}, {\"kind\": \"statement\", \"date\": \"2024-02-01\", \"source\": \"SH19 b\", \"total_after\": \"1100\"}, {\"kind\": \"consolidate\", \"date\": \"2024-03-01\", \"source\": \"SH02 c\", \"old_total\": \"1100\", \"total_after\": \"110\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"500\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"allot\", \"date\": \"2024-05-01\", \"source\": \"SH01 x\", \"allotted\": \"50\", \"total_after\": \"550\"}, {\"kind\": \"allot\", \"date\": \"2024-05-01\", \"source\": \"SH01 y\", \"allotted\": \"25\", \"total_after\": \"525\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"500\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"allot\", \"date\": \"2024-05-01\", \"source\": \"SH01 x\", \"allotted\": \"50\", \"total_after\": \"999\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"500\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"statement\", \"date\": \"2024-05-01\", \"source\": \"SH19 q\", \"total_after\": \"400\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"100.00\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"consolidate\", \"date\": \"2024-06-01\", \"source\": \"SH02 z\", \"old_total\": \"100.00\", \"total_after\": \"4.0\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"100\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"consolidate\", \"date\": \"2024-06-01\", \"source\": \"SH02 z\", \"old_total\": \"100\", \"total_after\": \"30\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"100\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"split\", \"date\": \"2024-06-01\", \"source\": \"X\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"100\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"allot\", \"date\": \"2024-13-01\", \"source\": \"X\", \"allotted\": \"1\", \"total_after\": \"101\"}]}",
                "POST /calc/share-ledger|{\"opening\": \"100\", \"opening_source\": \"SH00\", \"events\": [{\"kind\": \"allot\", \"date\": \"2024-03-01\", \"source\": \"late\", \"allotted\": \"5\", \"total_after\": \"105\"}, {\"kind\": \"allot\", \"date\": \"2024-02-01\", \"source\": \"early\", \"allotted\": \"1\"}]}",
                "POST /calc/comps|{\"target\": \"Zeta\", \"peers\": [\"PeerA\", \"PeerB\", \"PeerC\", \"Zeta\"], \"period\": \"FY24\", \"metrics\": [\"revenue\"]}",
                "POST /calc/comps|{\"target\": \"Other\", \"peers\": [\"PeerA\", \"PeerB\", \"PeerC\"], \"period\": \"FY24\", \"metrics\": [\"revenue\", \"ebitda\"]}",
                "POST /calc/comps|{\"target\": \"Zeta\", \"peers\": [\"PeerA\", \"PeerC\"], \"period\": \"FY24\", \"metrics\": [\"revenue\"]}",
                "POST /calc/comps|{\"target\": \"Zeta\", \"peers\": [\"PeerA\", \"PeerB\", \"PeerC\"], \"period\": \"FY24\", \"metrics\": [\"revenue\"], \"target_period\": \"FY23\"}",
                "POST /calc/comps|{\"target\": \"Zeta\", \"peers\": [\"PeerA\", \"PeerB\", \"PeerC\"], \"period\": \"FY24\", \"metrics\": [\"revenue\"], \"ev_period\": \"FY23\"}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"1\"], \"b\": [\"1\"]}, \"base\": [\"0\", \"0\"], \"total\": [\"1\", \"1\"]}",
                "POST /calc/tieout|{\"rows\": {\"a\": [null, \"2.00\"]}, \"base\": [\"0\", \"0\"], \"total\": [\"0\", \"2.00\"]}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"0.00\"]}, \"base\": [\"0\"], \"total\": [\"0\"]}",
                "POST /calc/tieout|{\"rows\": {}, \"base\": [\"1\"], \"total\": [\"1\"]}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"1\"]}, \"base\": [\"0\", \"0\"], \"total\": [\"1\", \"2\", \"3\"]}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"1\", \"2\", \"3\"]}, \"base\": [\"0\"], \"total\": [\"0\"]}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"1\"], \"b\": [\"1\"]}, \"base\": [\"0\", \"0\"], \"total\": [\"5\", \"5\"]}",
                "POST /calc/tieout|{\"rows\": {\"a\": [\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\"], \"b\": [\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\",\"1\"]}, \"base\": [\"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\", \"0\"], \"total\": [\"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\", \"1\"]}",
                "/calc/net-debt-adjusted?entity=Levered&period=FY24",
                "/calc/net-debt-adjusted?entity=Levered&period=FY24&include_leases=0",
                "/calc/net-debt-adjusted?entity=Levered&period=FY23",
                "/calc/net-debt-adjusted?entity=Zeta&period=FY24",
                "/documents",
                "/memo/versions?entity=Other",
                "/memo/versions/1",
            ]:
                requests.append((path, name))
        requests.append((f"DELETE /admin/keys/{REVOKE_KID}", "ADMIN"))
        requests.append(("DELETE /admin/keys/nope", "ADMIN"))
        # The directory is the local fake Graph (parity/fake_graph.py) for both stacks.
        requests.append((f"POST /admin/tenants/{TENANT_ID}/keys/nope/groups/sync|{{\"token\": \"t\"}}", "ADMIN"))
        requests.append((f"POST /admin/tenants/{TENANT_ID}/keys/{REVOKE_KID}/groups/sync|{{\"token\": \"t\"}}", "ADMIN"))
        requests.append((f"POST /admin/tenants/{TENANT_ID}/keys/{ADMIN_KID}/groups/sync|{{\"token\": \"t\"}}", "ADMIN"))
        requests.append((f"POST /admin/tenants/{TENANT_ID}/keys/{ADMIN_KID}/groups/sync|{{\"token\": \"t\"}}", "NOTOKEN"))
        requests.append((f"POST /admin/tenants/{TENANT_ID}/keys/{GRAPH_KID}/groups/sync|{{\"token\": \"t\"}}", "ADMIN"))
        for body in [{"role": "viewer", "deals": ["Other"], "deal_roles": {"Other": "partner"}},
                     {}, {"identity": "Ana@Example.test", "groups": ["G1", "g1", " g2 "]}]:
            requests.append((f"POST /admin/tenants/{TENANT_ID}/keys|{json.dumps(body)}", "ADMIN"))
        for body in [{"role": "nope"}, {"role": "analyst", "deals": ["Other"], "deal_roles": {"Zeta": "partner"}},
                     {"deal_roles": {"Other": "boss"}}]:
            requests.append((f"POST /admin/tenants/{TENANT_ID}/keys|{json.dumps(body)}", "ADMIN"))
        requests.append(("POST /admin/tenants/nope/keys|{}", "ADMIN"))
        requests.append((f"POST /admin/tenants/{TENANT_ID}/keys|{{}}", "NOTOKEN"))
        requests.append(("POST /admin/tenants|{\"name\": \"Acme\"}", "ADMIN"))
        requests.append(("POST /admin/tenants|{\"name\": \"Acme\"}", "NOTOKEN"))
        for flag in [True, False]:
            requests.append((f"PUT /admin/tenants/{TENANT_ID}/pii-redaction|{json.dumps({'on': flag})}", "ADMIN"))
        requests.append((f"PUT /admin/tenants/{TENANT_ID}/pii-redaction|{json.dumps({'on': 'yes'})}", "ADMIN"))
        requests.append(("PUT /admin/tenants/nope/pii-redaction|{\"on\": true}", "ADMIN"))
        requests.append((f"PUT /admin/tenants/{TENANT_ID}/pii-redaction|{json.dumps({'on': True})}", "NOTOKEN"))
        requests.append((f"DELETE /admin/keys/{REVOKE_KID}", "NOTOKEN"))
        for route in ["/admin/tenants/{t}/keys", "/admin/tenants/{t}/document-access"]:
            for who, tid in [("ADMIN", TENANT_ID), ("ADMIN", "nope"), ("NOTOKEN", TENANT_ID), ("admin", TENANT_ID)]:
                requests.append((route.format(t=tid), who))
        failures = 0
        for path, who in requests:
            body = None
            method, path = path.split(" ", 1) if path.startswith(("DELETE ", "PUT ", "POST ")) else ("GET", path)
            if method in ("PUT", "POST"):
                path, body = path.split("|", 1)
                body = json.loads(body)
            key = keys.get(who) if who else None
            hdr = {"X-Admin-Token": ADMIN_TOKEN} if who == "ADMIN" else None
            results = {}
            for label, base in [("fastapi", FA), ("rust", RS)]:
                marker = audit_marker(conn)
                status, resp = call(base, path, key, method=method, body=body, headers=hdr)
                status, resp = status, normalize_generated(method, path, resp)
                results[label] = (status, resp, audit_since(conn, marker))
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
