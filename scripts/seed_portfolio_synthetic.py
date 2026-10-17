"""Seed one portfolio holding, one target with a note, and its budget and mark figures for the demo.
  python scripts/seed_portfolio_synthetic.py http://localhost:8000 API_KEY

Everything here is SYNTHETIC: the holding, the target and its figures are invented. They are cited to a
synthetic portfolio pack uploaded with the demo, so /facts checks each quote on its page like any other figure.
Budget facts carry basis "budget", so they never mix with actual figures in the fact conflict check.
Run once on a fresh database; a second run adds a second holding and target.
"""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

BASE, KEY = sys.argv[1].rstrip("/"), sys.argv[2]
H = {"Authorization": "Bearer " + KEY}
M = 10**6
HOLDING = "Synthetic Holdco (SYNTHETIC)"
TARGET = "Synthetic Target Co (SYNTHETIC)"

PACK_LINES = [
    "SYNTHETIC portfolio pack. Not a real company. Figures in USD millions.",
    "Revenue actual 2025 405.0",
    "Revenue budget 2025 420.0",
    "Contributions actual 2025 10.0",
    "Distributions actual 2025 4.0",
    "Equity value 2024 310.0",
    "Equity value 2025 330.0",
]


WIDE_ROW = ("Revenue forecast 2026", "430.0")


def pack_pdf(path: str) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path)
    y = 780
    for line in PACK_LINES:
        c.drawString(72, y, line)
        y -= 24
    # A wide row: the label and figure sit far apart, so plain text splits them but layout text keeps the row.
    # The fact cut from it is stored as unverified, for the review queue.
    c.drawString(72, y, WIDE_ROW[0])
    c.drawString(450, y, WIDE_ROW[1])
    c.save()


def call(method, path, body=None, raw=None, ctype=None):
    h = dict(H)
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


def upload_pack() -> str:
    path = os.path.join(tempfile.mkdtemp(), "SYNTHETIC_portfolio_pack.pdf")
    pack_pdf(path)
    b = uuid.uuid4().hex
    head = (f'--{b}\r\nContent-Disposition: form-data; name="deal"\r\n\r\nProject Orchard\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="SYNTHETIC_portfolio_pack.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n").encode()
    with open(path, "rb") as f:
        raw = head + f.read() + f"\r\n--{b}--\r\n".encode()
    s, d = call("POST", "/documents", raw=raw, ctype=f"multipart/form-data; boundary={b}")
    if s != 200:
        sys.exit(f"upload pack failed: {s} {d}")
    return d["id"]


# (metric, period, USD millions, basis, quote, kind for the observation or None)
FIGURES = [
    ("revenue", "2025", 405, "GAAP", "Revenue actual 2025 405.0", "actual"),
    ("revenue", "2025", 420, "budget", "Revenue budget 2025 420.0", "budget"),
    ("contributions", "2025", 10, "GAAP", "Contributions actual 2025 10.0", "actual"),
    ("distributions", "2025", 4, "GAAP", "Distributions actual 2025 4.0", "actual"),
    ("equity_value", "2024", 310, "GAAP", "Equity value 2024 310.0", "mark"),
    ("equity_value", "2025", 330, "GAAP", "Equity value 2025 330.0", "mark"),
]
# Layout-only: the quote matches only layout text, so /facts stores it unverified and it waits in the review queue.
LAYOUT_ONLY = ("revenue", "2026", 430, "forecast", "Revenue forecast 2026 430.0")

doc = upload_pack()
s, company = call("POST", "/portfolio/companies", {"name": HOLDING, "sector": "Industrials",
                                                    "ownership_pct": "2.5"})
if s != 201:
    sys.exit(f"holding failed: {s} {company}")
cid = company["id"]
for metric, period, value, basis, quote, kind in FIGURES:
    s, fact = call("POST", "/facts", {"entity": HOLDING, "metric": metric, "period": period,
                                       "value": str(value * M), "unit": "USD", "document_id": doc, "page": 1,
                                       "quote": quote, "scale": str(M), "basis": basis})
    if s != 201:
        print(f"fact {metric} {period} rejected: {fact}")
        continue
    call("POST", f"/facts/{fact['id']}/review", {"action": "accept"})
    s, obs = call("POST", f"/portfolio/companies/{cid}/observations?fact_id={fact['id']}&kind={kind}")
    print(f"{kind} {metric} {period}: {'ok' if s in (200, 201) else obs}")

metric, period, value, basis, quote = LAYOUT_ONLY
s, fact = call("POST", "/facts", {"entity": HOLDING, "metric": metric, "period": period, "value": str(value * M),
                                   "unit": "USD", "document_id": doc, "page": 1, "quote": quote,
                                   "scale": str(M), "basis": basis})
print("layout-only fact:", fact.get("status") if s == 201 else fact)

s, _ = call("POST", "/targets", [{"name": TARGET, "source": "manual", "source_ref": "SYNTH-001",
                                  "sector": "Industrials", "country": "GB"}])
s, targets = call("GET", "/targets?q=Synthetic")
tid = next((t["id"] for t in (targets if isinstance(targets, list) else targets.get("items", []))
            if t.get("name") == TARGET), None)
if tid is not None:
    s, note = call("POST", f"/targets/{tid}/notes", {"body": "SYNTHETIC note: first call went well, "
                                                             "management wants a valuation range before IC."})
    print("target note:", "ok" if s == 201 else note)
else:
    print("target not found after import")
