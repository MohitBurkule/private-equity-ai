"""Seed two SYNTHETIC memo drafts that differ, so the memo versions card shows a real figure change and a source
change in the demo.
  python scripts/seed_memo_synthetic.py http://localhost:8000 API_KEY

Everything here is SYNTHETIC: the entity, the uploaded CSVs and the figures are invented. The first draft cites
revenue 405.0 for 2025; the second cites 410.0 after the first fact is rejected. Run once on a fresh database; a
second run adds two more drafts to the same entity.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE, KEY = sys.argv[1].rstrip("/"), sys.argv[2]
H = {"Authorization": "Bearer " + KEY}
ENTITY = "SYNTHETIC Holdco"
FIRST_CSV = b"Line item,Period,Value\nRevenue,2025,405.0\nRevenue,2024,380.0\n"
SECOND_CSV = b"Line item,Period,Value\nRevenue,2025,410.0\n"


def call(method, path, body=None, raw=None, ctype=None):
    h = dict(H)
    data = raw
    if body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def upload_csv(content: bytes, filename: str) -> str:
    b = uuid.uuid4().hex
    head = (f'--{b}\r\nContent-Disposition: form-data; name="deal"\r\n\r\n{ENTITY}\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: text/csv\r\n\r\n").encode()
    raw = head + content + f"\r\n--{b}--\r\n".encode()
    status, body = call("POST", "/documents", raw=raw, ctype=f"multipart/form-data; boundary={b}")
    if status != 200:
        sys.exit(f"upload {filename} failed: {status} {body}")
    return body["id"]


def add_fact(doc_id: str, period: str, value: str, quote: str) -> int:
    status, body = call("POST", "/facts", {"entity": ENTITY, "metric": "revenue", "period": period, "value": value,
                                           "unit": "USD m", "document_id": doc_id, "page": 1, "quote": quote})
    if status != 201:
        sys.exit(f"fact {period} {value} failed: {status} {body}")
    return body["id"]


def save_version() -> int:
    status, body = call("POST", f"/memo/versions?entity={urllib.parse.quote(ENTITY)}")
    if status != 201:
        sys.exit(f"memo version failed: {status} {body}")
    return body["id"]


def main() -> int:
    first_doc = upload_csv(FIRST_CSV, "synthetic_first.csv")
    old_fact = add_fact(first_doc, "2025", "405.0", "405.0")
    add_fact(first_doc, "2024", "380.0", "380.0")
    v_first = save_version()

    second_doc = upload_csv(SECOND_CSV, "synthetic_second.csv")
    status, body = call("POST", f"/facts/{old_fact}/review", {"action": "reject", "note": "SYNTHETIC revision"})
    if status != 200:
        sys.exit(f"reject failed: {status} {body}")
    add_fact(second_doc, "2025", "410.0", "410.0")
    v_second = save_version()

    status, diff = call("GET", f"/memo/versions/diff?from_id={v_first}&to_id={v_second}")
    if status != 200:
        sys.exit(f"diff failed: {status} {diff}")
    print(f"drafts {v_first} and {v_second}: {len(diff['figure_changes'])} figure change(s), "
          f"{len(diff['claim_changes']['added'])} claim line(s) added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
