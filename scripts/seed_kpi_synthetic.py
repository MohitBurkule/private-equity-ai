"""Seed a SYNTHETIC monthly revenue pack for one company whose last month jumps far outside its usual move, so the
KPI outlier alert shows in the inbox of the demo.
  python scripts/seed_kpi_synthetic.py http://localhost:8000 API_KEY

Everything here is SYNTHETIC: the company, the workbook and the figures are invented. Nine steady months move within
about 2% of each other; the tenth jumps by about 53%. The pack goes through the KPI pack upload, the only path that
judges a move against history. Run once on a fresh database.
"""
import io
import json
import sys
import urllib.error
import urllib.request
import uuid

from openpyxl import Workbook

BASE, KEY = sys.argv[1].rstrip("/"), sys.argv[2]
H = {"Authorization": "Bearer " + KEY}
ENTITY = "SYNTHETIC KPI Co"
MONTHS = [("2025-01", 100.0), ("2025-02", 102.0), ("2025-03", 101.0), ("2025-04", 103.0),
          ("2025-05", 102.5), ("2025-06", 104.0), ("2025-07", 103.5), ("2025-08", 105.0),
          ("2025-09", 104.5), ("2025-10", 160.4)]


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


def pack_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["SYNTHETIC monthly pack"])
    ws.append([])
    ws.append(["Metric", "Period", "Value", "Unit"])
    for period, value in MONTHS:
        ws.append(["Revenue", period, value, "USD m"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_pack(company_id: int) -> dict:
    data, name = pack_xlsx(), "synthetic_kpi_pack.xlsx"
    b = uuid.uuid4().hex
    head = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n").encode()
    raw = head + data + f"\r\n--{b}--\r\n".encode()
    status, body = call("POST", f"/portfolio/companies/{company_id}/kpi-pack", raw=raw,
                        ctype=f"multipart/form-data; boundary={b}")
    if status != 200:
        sys.exit(f"kpi pack failed: {status} {body}")
    return body


def main() -> int:
    status, body = call("POST", "/portfolio/companies", {"name": ENTITY, "sector": "SYNTHETIC", "sic": "3569"})
    if status != 201:
        sys.exit(f"company failed: {status} {body}")
    out = upload_pack(body["id"])
    print(f"synthetic kpi: {len(out.get('observations', []))} observations, last month jumps to 160.4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
