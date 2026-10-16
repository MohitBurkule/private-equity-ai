"""Fill a running local API with a small demo tenant so the UI has something to show (stdlib only).

  python scripts/seed_demo.py http://localhost:8000 ADMIN_TOKEN

Prints the new API key; paste it into the web app. The demo document is a generated one-page PDF
saying 'Net income 150', so every fact below cites a real page and quote. Not real company data.
"""
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE, ADMIN = sys.argv[1].rstrip("/"), sys.argv[2]


def call(method, path, headers=None, body=None, raw=None, ctype=None):
    h = dict(headers or {})
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
        return e.code, json.loads(e.read() or b"null")


def pdf(text: str) -> bytes:
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            None, b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    stream = b"BT /F1 12 Tf 20 100 Td (" + text.encode() + b") Tj ET"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + (o or b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream") + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def must(res, ok, what):
    if res[0] not in ok:
        sys.exit(f"{what} failed: {res}")
    return res[1]


t = must(call("POST", "/admin/tenants", {"X-Admin-Token": ADMIN}, {"name": "demo-" + uuid.uuid4().hex[:6]}), (201,), "tenant")
h = {"Authorization": "Bearer " + t["api_key"]}
b = uuid.uuid4().hex
raw = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="demo.pdf"\r\n'
       "Content-Type: application/pdf\r\n\r\n").encode() + pdf("Net income 150") + f"\r\n--{b}--\r\n".encode()
doc = must(call("POST", "/documents", h, raw=raw, ctype=f"multipart/form-data; boundary={b}"), (200,), "upload")
must(call("POST", "/facts", h, {"entity": "DemoCo", "metric": "net_income", "period": "FY", "value": "150",
                                "unit": "USD", "document_id": doc["id"], "page": 1, "quote": "Net income 150"}), (201,), "fact")
call("POST", "/deals", h, {"name": "Project Demo"})
print("API key:", t["api_key"])
print("Try:", f"curl -H 'Authorization: Bearer {t['api_key']}' '{BASE}/memo?entity=DemoCo'")
