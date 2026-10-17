"""Seed a running local API with verified facts from full inline-XBRL 10-Ks, through the normal /facts path.
  python scripts/seed_ixbrl_facts.py http://localhost:8000 ADMIN_TOKEN DATA_DIR/filings
Each figure is found by its iXBRL tag, so the value and the page come from the filing itself. Each row
label must appear in the figure's table row, so a total is never taken from a component line. /facts
then checks the quote and the number on the cited page before storing the fact. Prints the new API key.
Needs apps/api on the path (for app.ixbrl_full).
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
from app.ixbrl_full import figures, read_filing  # noqa: E402

BASE, ADMIN, FOLDER = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
FY = "2019-01-01/2019-12-31"
FY25 = "2025-01-01/2025-12-31"
# (file, entity, [(metric, period label, [concepts to try], period_key, row label)])
FILINGS = [
    ("3M_2019_10K.htm", "3M Company", [
        ("revenue", "FY2019", ["us-gaap:Revenues"], FY, "Net sales"),
        ("revenue", "FY2018", ["us-gaap:Revenues"], "2018-01-01/2018-12-31", "Net sales"),
        ("net_income", "FY2019", ["us-gaap:NetIncomeLoss"], FY, "Net income attributable to 3M"),
        ("operating_income", "FY2019", ["us-gaap:OperatingIncomeLoss"], FY, "Operating income"),
        ("total_assets", "FY2019", ["us-gaap:Assets"], "@2019-12-31", "Total assets"),
        ("cash", "FY2019", ["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "@2019-12-31", "Cash and cash equivalents"),
        ("long_term_debt", "FY2019", ["us-gaap:LongTermDebtNoncurrent"], "@2019-12-31", "Long-term debt"),
    ]),
    ("filings/Hertz_10-K_2025-12-31.htm", "Hertz Global Holdings", [
        ("revenue", "FY2025", ["us-gaap:Revenues"], FY25, "Revenues"),
        ("total_assets", "FY2025", ["us-gaap:Assets"], "@2025-12-31", "Total assets"),
        ("cash", "FY2025", ["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "@2025-12-31", "Cash and cash equivalents"),
    ]),
    ("filings/SoteraHealth_10-K_2025-12-31.htm", "Sotera Health Company", [
        ("net_income", "FY2025", ["us-gaap:NetIncomeLoss"], FY25, "Net income"),
        ("total_assets", "FY2025", ["us-gaap:Assets"], "@2025-12-31", "Total assets"),
        ("cash", "FY2025", ["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "@2025-12-31", "Cash and cash equivalents"),
    ]),
]


def call(method, path, headers=None, body=None, raw=None, ctype=None):
    h = dict(headers or {})
    data = raw
    if body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def must(res, ok, what):
    if res[0] not in ok:
        sys.exit(f"{what} failed: {res}")
    return res[1]


def multipart(path):
    b = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    head = (
        f'--{b}\r\nContent-Disposition: form-data; name="deal"\r\n\r\nProject Orchard\r\n'
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'
        "Content-Type: text/html\r\n\r\n"
    ).encode()
    return head + data + f"\r\n--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


tenant = must(
    call("POST", "/admin/tenants", {"X-Admin-Token": ADMIN}, {"name": "ixbrl-" + uuid.uuid4().hex[:6]}),
    (201,),
    "tenant",
)
h = {"Authorization": "Bearer " + tenant["api_key"]}
must(call("POST", "/deals", h, {"name": "Project Orchard"}), (201,), "deal")

SECTORS = {"3M Company": "Industrials", "Hertz Global Holdings": "Consumer", "Sotera Health Company": "Healthcare"}
seeded = {}  # entity -> fact ids, so each entity gets a portfolio holding with its KPIs as observations

for name, entity, wanted in FILINGS:
    path = os.path.join(FOLDER, name)
    raw, ctype = multipart(path)
    doc = must(call("POST", "/documents", h, raw=raw, ctype=ctype), (200,), f"upload {name}")["id"]
    with open(path, encoding="utf-8", errors="replace") as f:
        _, tags = read_filing(f.read())
    for metric, period, concepts, period_key, label in wanted:
        hits = [t for c in concepts for t in figures(tags, c, period_key) if label in t.row]
        if not hits:
            print(f"skip {entity} {metric} {period}: no tagged figure on row {label!r}")
            continue
        fig = hits[0]
        body = {
            "entity": entity,
            "metric": metric,
            "period": period,
            "value": str(int(fig.text.replace(",", "")) * 10**fig.scale),
            "unit": "USD",
            "document_id": doc,
            "page": fig.page,
            "quote": fig.row,
            "scale": 10**fig.scale,
        }
        fid = must(call("POST", "/facts", h, body), (201,), f"fact {entity} {metric} {period}")["id"]
        must(call("POST", f"/facts/{fid}/review", h, {"action": "accept"}), (200,), "review")
        seeded.setdefault(entity, []).append(fid)
        print(f"fact {entity} {metric} {period}: {fig.text} (p. {fig.page}) accepted")

for entity, fact_ids in seeded.items():
    company = must(
        call("POST", "/portfolio/companies", h,
             {"name": f"{entity} (demo holding)", "sector": SECTORS[entity], "ownership_pct": "2.5"}),
        (201,),
        f"portfolio {entity}",
    )
    for fid in fact_ids:
        must(call("POST", f"/portfolio/companies/{company['id']}/observations?fact_id={fid}", h),
             (200, 201), f"observation {entity}")

print("API key:", tenant["api_key"])
