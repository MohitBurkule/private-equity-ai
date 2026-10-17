"""Fill the demo with what the walkthrough shows, from local files only, so a fresh `make demo` reproduces it.

  python scripts/demo_extras.py API_URL API_KEY DB_URL DATA_DIR DEMO_DIR

1. Term Loan A covenant terms from the XPO exhibit in DATA_DIR/filings (skipped if the file is absent).
2. An LBO run with derived EBITDA and labelled assumptions, saved as a run in the app (lbo_run.json has the row).
3. One candidate watch run over a cached, dated EDGAR result (data/demo/cache). The firm screening rule is
   SYNTHETIC demo text, uploaded as its own document and labelled as such; it is not a real firm's rule.
Nothing personal is written. Re-running adds nothing new (facts and alerts are deduplicated).
"""
import json
import sys
import urllib.error
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
