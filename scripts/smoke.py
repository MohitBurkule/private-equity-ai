"""End-to-end smoke test against a running API (stdlib only).

  python scripts/smoke.py http://localhost:8000 ADMIN_TOKEN [path/to/10-K.pdf]

Creates a tenant, uploads a PDF (a generated one if none given), stores a cited fact that must
verify, confirms a fabricated fact is refused, builds the memo, checks tenant isolation with a
second tenant and verifies the audit chain. Exits non-zero on the first failure.
"""
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE, ADMIN = sys.argv[1].rstrip("/"), sys.argv[2]
PDF = sys.argv[3] if len(sys.argv) > 3 else None


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
        return e.code, json.loads(e.read() or b"null")


def upload(h, content, name="doc.pdf"):
    b = uuid.uuid4().hex
    body = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return call("POST", "/documents", h, raw=body, ctype=f"multipart/form-data; boundary={b}")


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)


def tenant(name):
    s, r = call("POST", "/admin/tenants", {"X-Admin-Token": ADMIN}, {"name": name})
    check(s == 201, f"create tenant {name}")
    return {"Authorization": "Bearer " + r["api_key"]}


def tiny_pdf():
    """Minimal one-page PDF whose text layer says: Net income 150"""
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]/Contents 4 0 R"
            "/Resources<</Font<</F1 5 0 R>>>>>>",
            None, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    stream = b"BT /F1 12 Tf 20 100 Td (Net income 150) Tj ET"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        body = o.encode() if o else b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream"
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


s, _ = call("GET", "/health")
check(s == 200, "health")
check(call("GET", "/documents")[0] == 401, "unauthenticated request refused")
a, b = tenant("smoke-a"), tenant("smoke-b")
content = open(PDF, "rb").read() if PDF else tiny_pdf()
s, doc = upload(a, content)
check(s == 200 and doc["n_pages"] >= 1, f"upload ({doc.get('n_pages')} pages)")
s, hits = call("GET", "/search?q=net+income", a)
check(s == 200 and hits, "search finds the document")
page, text = hits[0]["page"], call("GET", f"/documents/{doc['id']}/pages/{hits[0]['page']}", a)[1]["text"]
quote = "Net income 150" if not PDF else next(
    (ln.strip() for ln in text.splitlines() if "Net income" in ln and any(c.isdigit() for c in ln)), "")
check(bool(quote), f"found a quote on page {page}: {quote[:60]!r}")
num = "".join(ch for ch in quote.split()[-1] if ch.isdigit() or ch == ".") if quote else "0"
fact = {"entity": "Smoke", "metric": "net_income", "period": "FY", "value": num, "unit": "USD",
        "document_id": doc["id"], "page": page, "quote": quote}
s, r = call("POST", "/facts", a, fact)
check(s == 201, "cited fact accepted")
s, r = call("POST", "/facts", a, {**fact, "value": "999999"})
check(s == 422, "fabricated number refused")
s, r = call("GET", "/memo?entity=Smoke", a)
check(s == 200 and "[1]" in r["markdown"], "memo has a footnote")
check(call("GET", f"/documents/{doc['id']}/pages/{page}", b)[0] == 404, "other tenant cannot read the page")
check(call("GET", "/memo?entity=Smoke", b)[1]["markdown"].count("Nothing to report") == 1,
      "other tenant sees no facts")
s, r = call("GET", "/audit/verify", a)
check(s == 200 and r["ok"], "audit chain verifies")
print("SMOKE PASSED")
