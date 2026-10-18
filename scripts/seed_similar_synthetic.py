"""Seed three SYNTHETIC deals that share a SIC division and a sponsor, with IC decisions and a post-mortem, so the
deal workspace's "Similar past deals" card has something to show in the demo.
  python scripts/seed_similar_synthetic.py http://localhost:8000 API_KEY

Everything here is SYNTHETIC: the names, the sponsor, the decisions and the lesson are invented. No figures are
seeded. Run once on a fresh database; a second run reports the deals as already present and adds nothing.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE, KEY = sys.argv[1].rstrip("/"), sys.argv[2]
H = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
SPONSOR = "SYNTHETIC Capital Partners"
SIC = "3569"  # SIC division 35, machinery; the same division for all three so the rule matches

DEALS = [
    {"name": "SYNTHETIC Peer A", "stage": "closed", "sic": SIC, "sponsor": SPONSOR},
    {"name": "SYNTHETIC Peer B", "stage": "passed", "sic": SIC, "sponsor": SPONSOR},
    {"name": "SYNTHETIC Peer C", "stage": "sourcing", "sic": SIC, "sponsor": SPONSOR},
]

DECISIONS = [
    {"deal": "SYNTHETIC Peer A", "outcome": "proceed",
     "rationale": "SYNTHETIC rationale: margins held through the cycle and the add-on pipeline was credible."},
    {"deal": "SYNTHETIC Peer B", "outcome": "pass",
     "rationale": "SYNTHETIC rationale: customer concentration too high for the leverage we would need.",
     "dissent": "SYNTHETIC dissent: the pass was close, and the concentration risk could be priced rather than avoided.",
     "dissenter": "SYNTHETIC Partner"},
]

POSTMORTEMS = [
    {"deal": "SYNTHETIC Peer A", "outcome": "exited",
     "lesson": "SYNTHETIC lesson: the add-on pipeline was the value driver; underwrite it separately from organic growth."},
]


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main() -> int:
    for d in DEALS:
        status, body = call("POST", "/deals", d)
        print(f"deal {d['name']}: {'created' if status == 201 else f'status {status} {body}'}")
    for dec in DECISIONS:
        status, body = call("POST", "/ic/decisions", dec)
        print(f"decision {dec['deal']}: {status}")
        if status != 201:
            return 1
    for pm in POSTMORTEMS:
        status, body = call("POST", f"/deals/{urllib.parse.quote(pm['deal'])}/postmortems", pm)
        print(f"postmortem {pm['deal']}: {status}")
        if status != 201:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
