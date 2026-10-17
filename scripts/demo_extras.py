"""Fill the demo with what the walkthrough shows, from local files only, so a fresh `make demo` reproduces it.

  python scripts/demo_extras.py API_URL API_KEY DB_URL DATA_DIR DEMO_DIR

1. Term Loan A covenant terms from the XPO exhibit in DATA_DIR/filings (skipped if the file is absent).
2. An LBO run with derived EBITDA and labelled assumptions, saved as a run in the app (lbo_run.json has the row).
2b. The one-click flagship run on the XPO FY2025 10-K (flagship_run.json) and its legal step on Amendment No. 11.
3. One candidate watch run over a cached, dated EDGAR result (data/demo/cache). The firm screening rule is
   SYNTHETIC demo text, uploaded as its own document and labelled as such; it is not a real firm's rule.
Nothing personal is written. Re-running adds nothing new (facts and alerts are deduplicated).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API, KEY, DB_URL, DATA, DEMO = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5])
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def call(method, path, body=None, raw=None, ctype=None):
    h = {"Authorization": "Bearer " + KEY}
    data = raw
    if body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(API + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:200]}


def upload(path: Path, ctype: str):
    b = "----demo" + path.name.replace(".", "")
    head = (f'--{b}\r\nContent-Disposition: form-data; name="deal"\r\n\r\nProject Orchard\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode()
    raw = head + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    return call("POST", "/documents", raw=raw, ctype=f"multipart/form-data; boundary={b}")


# 1. Term Loan A terms
tla = DATA / "filings" / "XPO_Ex10-2_TermLoanA_Agreement_2026-06.htm"
if tla.exists():
    doc = upload(tla, "text/html")
    print("term loan A:", call("POST", f"/documents/{doc['id']}/credit-agreement/facts").get("created", doc))
else:
    print("term loan A: exhibit not in DATA_DIR, skipped")

# 2. LBO run: EBITDA derived from cited facts, every other input a labelled assumption
A = {"set_by": "deal team", "set_on": "2026-10-17", "reason": "demo base case, not a sourced figure"}
inputs = {"ebitda": {"derived": {"formula": "ebitda", "entity": "3M Company", "period": "FY2019"}}}
for k, v in {"entry_multiple": "10", "exit_multiple": "11", "leverage": "5", "interest_rate": "8",
             "tax_rate": "25", "cash_conversion": "60", "fees_pct": "2", "years": "5"}.items():
    inputs[k] = {"value": v, "assumption": A}
AXIS = ["8", "9", "10", "11", "12"]
request = {"inputs": inputs, "entry_multiples": AXIS, "exit_multiples": AXIS}
# Saved through /lbo/runs so the LBO screen opens on it and history/compare have a run to show.
saved = call("POST", "/lbo/runs", {"name": "3M base case (demo assumptions)", "request": request})
(DEMO / "lbo_run.json").write_text(json.dumps(saved, indent=1))
print("lbo run:", {k: saved.get(k) for k in ("name", "moic", "irr", "error")})

# 2b. One-click flagship on the XPO FY2025 10-K: tagged facts, comps, precedents, LBO, memo. Each step reports its
#     own status. Legal reads the Amendment No. 11 exhibit in a second call, since one flagship call reads one document.
LBO_ASSUMPTIONS = {
    "entry_multiple": ("12", "illustrative entry multiple of EBITDA"),
    "exit_multiple": ("12", "exit at entry multiple"),
    "leverage": ("5", "illustrative leverage, x EBITDA"),
    "interest_rate": ("0.08", "illustrative cost of debt"),
    "tax_rate": ("0.21", "US federal statutory rate"),
    "cash_conversion": ("0.7", "illustrative FCF / EBITDA"),
    "fees_pct": ("0.02", "illustrative deal fees"),
    "years": ("5", "holding period"),
}
flag_lbo = {k: {"value": v, "assumption": why} for k, (v, why) in LBO_ASSUMPTIONS.items()}
tenk = DATA / "filings" / "XPO_10-K_FY2025.htm"
amend = DATA / "filings" / "XPO_Ex10-1_CreditAgreementAmend11_2026-05.htm"
if tenk.exists():
    base = {"entity": "XPO", "extract": True, "sic": "4213", "cik": "1166003", "peers_pages": 1,
            "precedents": {"since": "2025-10-17", "until": "2026-10-16", "limit": 3}, "lbo": {"inputs": flag_lbo}}
    doc = upload(tenk, "text/html")
    flag = call("POST", "/flagship/run", {**base, "document_id": doc["id"]})
    (DEMO / "flagship_run.json").write_text(json.dumps(flag, indent=1))
    print("flagship:", {s["step"]: s["status"] for s in flag.get("steps", [])} or flag)
    # Peer enterprise values from a market-data feed, cited to each feed record. Defaults to the SYNTHETIC WireMock
    # feed on https://localhost:8443 (compose or make demo-mocks). The API must trust the mock's self-signed CA:
    # start it with SSL_CERT_FILE=deploy/mocks/tls/out/cert.pem.
    tmpl = os.environ.get("MARKET_FEED_URL_TEMPLATE", "https://localhost:8443/v2/tev?symbol={name}")
    token = os.environ.get("MARKET_FEED_TOKEN", "synthetic-token")
    comps = next((st for st in flag.get("steps", []) if st["step"] == "comps"), {})
    if comps.get("status") == "ok":
        for peer in comps["result"]["peers"]:
            call("POST", "/market/tev-sync", {"entity": peer["name"], "period": "LTM", "source": os.environ.get("MARKET_FEED_SOURCE", "SYNTHETIC-market-feed"),
                                              "url": tmpl.format(name=urllib.parse.quote(peer["name"])), "token": token})
        flag = call("POST", "/flagship/run", {**base, "document_id": doc["id"]})
        (DEMO / "flagship_run.json").write_text(json.dumps(flag, indent=1))
        print("flagship with peer EV:", {s["step"]: s["status"] for s in flag.get("steps", [])} or flag)
    else:
        print("peer EV: MARKET_FEED_URL_TEMPLATE / MARKET_FEED_TOKEN not set, peers listed without EV")
    if amend.exists():
        legal_doc = upload(amend, "text/html")
        legal = call("POST", "/flagship/run", {"entity": "XPO", "document_id": legal_doc["id"], "legal_doc_type": "credit"})
        (DEMO / "flagship_legal.json").write_text(json.dumps(legal, indent=1))
        print("flagship legal:", {s["step"]: s["status"] for s in legal.get("steps", [])} or legal)
else:
    print("flagship: XPO 10-K not in DATA_DIR, skipped")

# 3. Candidate watch over the cached EDGAR result, with a synthetic firm rule
from sqlalchemy import select  # noqa: E402

from app import alerts as al  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import Document, Fact, FirmKnowledge  # noqa: E402

RULE = ("Demo screening rule (SYNTHETIC, not a real firm document): "
        "we review a deal only if the company operates in software or business services in the United States or Canada.")
rule_html = DEMO / "synthetic_firm_rule.htm"
rule_html.write_text(f"<html><body><p>{RULE}</p></body></html>")
rule_doc = upload(rule_html, "text/html")
engine = make_engine(DB_URL)
with make_session_factory(engine)() as db:
    tenant = db.execute(select(Fact.tenant_id).limit(1)).scalar_one()
    doc = db.get(Document, rule_doc.get("id", ""))
    if doc is None:
        print("candidate watch: rule document not stored, skipped")
    else:
        if db.query(FirmKnowledge).filter_by(tenant_id=tenant, key="deal_screening_criteria").first() is None:
            db.add(FirmKnowledge(tenant_id=tenant, key="deal_screening_criteria", value=RULE,
                                 document_id=doc.id, page=1, quote=RULE, status="accepted"))
            db.commit()
        cache = json.loads((ROOT / "data" / "demo" / "cache" / "edgar_candidates_2026-10-17.json").read_text())

        def cached(term, since, until):
            return [(i["name"], i["url"], f"{i['label']} (cached {cache['captured_on']})")
                    for i in cache["terms"].get(term, [])]

        made = al.scan_candidates(db, tenant, cached, None, "2025-10-17", "2026-10-17")
        print(f"candidate watch: {len(made)} new candidates from cached search {cache['captured_on']}")

# 4. XPO rate-move watch, end to end on cited inputs. Floating principal is read from the FY2025 10-K debt
# sentence; EBITDA is derived from operating income and D&A; the interest-cover minimum is the Term Loan A
# covenant (section 7.11(c)), created from the exhibit in step 1. Each fact is verified through /facts.
from app import debt_parse  # noqa: E402
from app.ixbrl_full import read_filing  # noqa: E402

tenk = DATA / "filings" / "XPO_10-K_FY2025.htm"
if tenk.exists() and tla.exists():
    tenk_doc = upload(tenk, "text/html")
    pages, _ = read_filing(tenk.read_text(encoding="utf-8", errors="replace"))
    numbered = [(int(p.label.split()[1]), p.text) for p in pages]
    for row in debt_parse.floating_principal(numbered):
        fact = call("POST", "/facts", {"entity": "XPO", "metric": "floating_rate_debt", "period": "FY2025",
                                       "value": str(row["amount"]), "unit": "USD", "document_id": tenk_doc["id"],
                                       "page": row["page"], "quote": row["quote"], "scale": 1000000})
        if "id" in fact:
            call("POST", f"/facts/{fact['id']}/review", {"action": "accept"})
        print("xpo floating principal:", fact.get("id", fact), row["quote"][:60])
    with make_session_factory(engine)() as db:
        thr = db.execute(select(Fact.id).where(Fact.metric == "covenant interest_coverage minimum")
                         .order_by(Fact.id.desc())).scalars().first()
    if thr is not None:
        co = call("POST", "/portfolio/companies", {"name": "XPO", "sector": "Industrials"})
        call("POST", f"/portfolio/companies/{co['id']}/covenants",
             {"kpi_metric": "interest_coverage", "operator": ">=", "threshold_fact_id": thr})
        print("xpo covenant:", "interest cover minimum from Term Loan A section 7.11(c), fact", thr)
    scan = call("POST", "/alerts/scan")
    rate = [a for a in scan.get("created", []) if a.get("kind") == "covenant_scenario"]
    print("xpo rate-move watch at the firm's shock:", rate or "no alert (cover stays above the minimum)")
else:
    print("xpo rate-move watch: FY2025 10-K or Term Loan A exhibit not in DATA_DIR, skipped")
