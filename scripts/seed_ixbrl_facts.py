"""Seed a running local API with verified facts from a full inline-XBRL 10-K, through the normal /facts path.
  python scripts/seed_ixbrl_facts.py http://localhost:8000 ADMIN_TOKEN FILING.htm
Each figure is found by its iXBRL tag, so the value and the page come from the filing itself; the
/facts endpoint then checks the quote on that page and the number in it before storing the fact.
Prints the new API key. Needs apps/api on the path (for app.ixbrl_full).
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
from app.ixbrl_full import figures, read_filing  # noqa: E402

BASE, ADMIN, FILING = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
ENTITY = "3M Company"
# (metric, period label, concept, start, end) for plain duration contexts of the filing's own year.
WANTED = [
    ("revenue", "FY2019", "us-gaap:Revenues", "2019-01-01", "2019-12-31"),
    ("revenue", "FY2018", "us-gaap:Revenues", "2018-01-01", "2018-12-31"),
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
raw, ctype = multipart(FILING)
doc = must(call("POST", "/documents", h, raw=raw, ctype=ctype), (200,), "upload 10-K")["id"]

with open(FILING, encoding="utf-8", errors="replace") as f:
    pages, tags = read_filing(f.read())
for metric, period, concept, start, end in WANTED:
    hits = figures(tags, concept, start, end)
    if not hits:
        sys.exit(f"no tagged {concept} for {period}")
    fig = hits[0]
    body = {
        "entity": ENTITY,
        "metric": metric,
        "period": period,
        "value": str(int(fig.text.replace(",", "")) * 10**6),
        "unit": "USD",
        "document_id": doc,
        "page": fig.page,
        "quote": fig.row,
        "scale": 10**6,
    }
    fid = must(call("POST", "/facts", h, body), (201,), f"fact {metric} {period}")["id"]
    must(call("POST", f"/facts/{fid}/review", h, {"action": "accept"}), (200,), "review")
    print(f"fact {metric} {period}: {fig.text} (p. {fig.page}) accepted")

print("API key:", tenant["api_key"])
