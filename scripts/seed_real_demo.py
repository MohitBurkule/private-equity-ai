"""Seed a running local API with real public filings, so the UI shows real numbers and real sources.

  python scripts/seed_real_demo.py http://localhost:8000 ADMIN_TOKEN DATA_DIR

DATA_DIR is a folder with sec/APPLE_2023Q3_10Q.pdf (Apple Q3 FY23 10-Q) and edgar/ (SEC companyfacts and
submissions JSON, e.g. companyfacts_Apple.json, submissions_Apple.json). Prints the new API key.

Every fact stores the quote and the page it was found on, and the code refuses a fact the page does not
contain. Needs `pdftotext` (poppler) on PATH. Stdlib only apart from that.
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from glob import glob

BASE, ADMIN, DATA = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]


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


def pages_of(pdf_path):
    text = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [re.sub(r"\s+", " ", p) for p in text.split("\f")]


def page_of(pages, quote):
    q = re.sub(r"\s+", " ", quote)
    for i, p in enumerate(pages):
        if q in p:
            return i + 1
    sys.exit(f"quote not found in any page: {quote!r}")


def multipart(path):
    b = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    head = (
        f'--{b}\r\nContent-Disposition: form-data; name="deal"\r\n\r\nProject Orchard\r\n'
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    return (
        head + data + f"\r\n--{b}--\r\n".encode(),
        f"multipart/form-data; boundary={b}",
    )


tenant = must(
    call(
        "POST",
        "/admin/tenants",
        {"X-Admin-Token": ADMIN},
        {"name": "demo-" + uuid.uuid4().hex[:6]},
    ),
    (201,),
    "tenant",
)
h = {"Authorization": "Bearer " + tenant["api_key"]}
must(call("POST", "/deals", h, {"name": "Project Orchard"}), (201,), "deal")

apple_pdf = os.path.join(DATA, "sec", "APPLE_2023Q3_10Q.pdf")
raw, ctype = multipart(apple_pdf)
doc = must(call("POST", "/documents", h, raw=raw, ctype=ctype), (200,), "upload 10-Q")[
    "id"
]
pages = pages_of(apple_pdf)

# Each quote is copied from the filing. The value is the figure in the quote, in millions, scaled to units.
FACTS = [
    (
        "net_income",
        "9M FY23",
        "74039",
        "Net income $ 19,881 $ 19,442 $ 74,039 $ 79,082",
    ),
    (
        "net_income",
        "9M FY22",
        "79082",
        "Net income $ 19,881 $ 19,442 $ 74,039 $ 79,082",
    ),
    ("net_sales", "Q3 FY23", "81797", "Total net sales $ 81,797"),
    ("total_liabilities", "Q3 FY23", "274764", "Total liabilities 274,764"),
    ("total_assets", "Q3 FY23", "335038", "Total assets $ 335,038"),
]
fact_ids = {}
for metric, period, millions, quote in FACTS:
    body = {
        "entity": "Apple Inc.",
        "metric": metric,
        "period": period,
        "value": str(int(millions) * 10**6),
        "unit": "USD",
        "document_id": doc,
        "page": page_of(pages, quote),
        "quote": quote,
        "scale": 10**6,
    }
    fid = must(call("POST", "/facts", h, body), (201,), f"fact {metric} {period}")["id"]
    must(
        call("POST", f"/facts/{fid}/review", h, {"action": "accept"}), (200,), "review"
    )
    fact_ids[(metric, period)] = fid

company = must(
    call(
        "POST",
        "/portfolio/companies",
        h,
        {"name": "Apple Inc. (demo holding)", "sector": "Tech", "ownership_pct": "2.5"},
    ),
    (201,),
    "portfolio",
)
for key in (("net_income", "9M FY23"), ("total_liabilities", "Q3 FY23")):
    must(
        call(
            "POST",
            f"/portfolio/companies/{company['id']}/observations?fact_id={fact_ids[key]}",
            h,
        ),
        (200, 201),
        "observation",
    )
must(
    call(
        "POST",
        f"/portfolio/companies/{company['id']}/covenants",
        h,
        {
            "kpi_metric": "net_income",
            "operator": ">=",
            "threshold_fact_id": fact_ids[("net_income", "9M FY22")],
        },
    ),
    (200, 201),
    "covenant",
)
must(
    call("POST", "/dd/requests/seed", h, {"deal": "Project Orchard"}),
    (200, 201),
    "dd seed",
)

# Sourcing targets: SEC companyfacts for every company in edgar/, with submissions where present.
edgar = os.path.join(DATA, "edgar")
imported = 0
for cf_path in sorted(glob(os.path.join(edgar, "companyfacts_*.json"))):
    with open(cf_path) as f:
        cf = json.load(f)
    sub_path = os.path.join(
        edgar, "submissions_" + os.path.basename(cf_path)[len("companyfacts_") :]
    )
    if os.path.exists(sub_path):
        with open(sub_path) as f:
            sub = json.load(f)
    else:
        sub = {"cik": cf["cik"], "name": cf["entityName"]}
    must(
        call(
            "POST", "/targets/import/sec", h, {"submissions": sub, "companyfacts": cf}
        ),
        (201,),
        cf_path,
    )
    imported += 1

print(
    f"Seeded: Project Orchard deal, Apple 10-Q ({len(FACTS)} cited facts), portfolio covenant, "
    f"{imported} SEC targets."
)
print("API key:", tenant["api_key"])
