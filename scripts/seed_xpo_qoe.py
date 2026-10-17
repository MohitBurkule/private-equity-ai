"""Seed the XPO quality-of-earnings, NWC peg and LBO tie examples into a running local API.
  python scripts/seed_xpo_qoe.py http://localhost:8000 API_KEY DATA_DIR/filings

Every figure is a fact cited to a page of the FY2025 or FY2024 10-K, and /facts checks each quote and number
on that page before storing it. The normalized EBITDA bridge is the Note 3 reconciliation, so its totals match
the 10-K's own adjusted EBITDA. The LBO workbook is synthetic: only the balance-sheet inputs are set to XPO's
figures, and it says so in its own cell. Run once on a fresh database; a second run posts duplicate facts.
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

BASE, KEY, FOLDER = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
H = {"Authorization": "Bearer " + KEY}
M = 10**6  # the filings report USD millions; facts are stored in USD


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
        return e.code, e.read().decode()[:400]


def upload(name):
    b = uuid.uuid4().hex
    with open(os.path.join(FOLDER, name), "rb") as f:
        data = f.read()
    head = (f'--{b}\r\nContent-Disposition: form-data; name="deal"\r\n\r\nProject Orchard\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: text/html\r\n\r\n").encode()
    s, d = call("POST", "/documents", raw=head + data + f"\r\n--{b}--\r\n".encode(),
                ctype=f"multipart/form-data; boundary={b}")
    if s != 200:
        sys.exit(f"upload {name} failed: {s} {d}")
    return d["id"]


BRIDGE_2025_2023 = "Income from continuing operations $ 316 $ 387 $ 192"
# (metric, period, USD millions, document key, page, quote). Bridge lines are Note 3 p. 65 of the FY2025 10-K.
ROWS = [
    ("ebitda_bridge reported", "2025", 316, "F25", 65, BRIDGE_2025_2023),
    ("ebitda_bridge reported", "2024", 387, "F25", 65, BRIDGE_2025_2023),
    ("ebitda_bridge reported", "2023", 192, "F25", 65, BRIDGE_2025_2023),
    ("ebitda_bridge add_back", "2025", 219, "F25", 65, "Interest expense 219 223 168"),
    ("ebitda_bridge add_back", "2024", 223, "F25", 65, "Interest expense 219 223 168"),
    ("ebitda_bridge add_back", "2023", 168, "F25", 65, "Interest expense 219 223 168"),
    ("ebitda_bridge add_back", "2025", 121, "F25", 65, "Income tax provision 121 86 68"),
    ("ebitda_bridge add_back", "2024", 86, "F25", 65, "Income tax provision 121 86 68"),
    ("ebitda_bridge add_back", "2023", 68, "F25", 65, "Income tax provision 121 86 68"),
    ("ebitda_bridge add_back", "2025", 521, "F25", 65, "Depreciation and amortization expense 521 490 432"),
    ("ebitda_bridge add_back", "2024", 490, "F25", 65, "Depreciation and amortization expense 521 490 432"),
    ("ebitda_bridge add_back", "2023", 432, "F25", 65, "Depreciation and amortization expense 521 490 432"),
    ("ebitda_bridge add_back", "2025", 6, "F25", 65, "Debt extinguishment loss 6 — 25"),
    ("ebitda_bridge add_back", "2023", 25, "F25", 65, "Debt extinguishment loss 6 — 25"),
    ("ebitda_bridge add_back", "2025", 35, "F25", 65, "Pre-Con-way acquisition environmental matter (1) 35 — —"),
    ("ebitda_bridge add_back", "2025", 8, "F25", 65, "Transaction and integration costs 8 53 58"),
    ("ebitda_bridge add_back", "2024", 53, "F25", 65, "Transaction and integration costs 8 53 58"),
    ("ebitda_bridge add_back", "2023", 58, "F25", 65, "Transaction and integration costs 8 53 58"),
    ("ebitda_bridge add_back", "2025", 59, "F25", 65, "Restructuring costs 59 27 44"),
    ("ebitda_bridge add_back", "2024", 27, "F25", 65, "Restructuring costs 59 27 44"),
    ("ebitda_bridge add_back", "2023", 44, "F25", 65, "Restructuring costs 59 27 44"),
    ("ebitda_bridge add_back", "2023", 1, "F25", 65, "Other — — 1"),
    # The 2025 legal item is a gain, so it enters as a negative add-back; the quote's "( 13 )" is the gain.
    ("ebitda_bridge add_back", "2025", -13, "F25", 65, "Legal matters (2) ( 13 ) — 8"),
    ("ebitda_bridge add_back", "2023", 8, "F25", 65, "Legal matters (2) ( 13 ) — 8"),
    # NWC inputs: 2025 and 2024 from the FY2025 10-K balance sheet, 2023 from the FY2024 10-K.
    ("current_assets", "2025", 1630, "F25", 47, "Total current assets 1,630 1,505"),
    ("current_assets", "2024", 1505, "F25", 47, "Total current assets 1,630 1,505"),
    ("current_assets", "2023", 1593, "F24", 49, "Total current assets 1,505 1,593"),
    ("cash", "2025", 310, "F25", 47, "Cash and cash equivalents $ 310 $ 246"),
    ("cash", "2024", 246, "F25", 47, "Cash and cash equivalents $ 310 $ 246"),
    ("cash", "2023", 412, "F24", 49, "Cash and cash equivalents $ 246 $ 412"),
    ("current_liabilities", "2025", 1555, "F25", 47, "Total current liabilities 1,555 1,420"),
    ("current_liabilities", "2024", 1420, "F25", 47, "Total current liabilities 1,555 1,420"),
    ("current_liabilities", "2023", 1590, "F24", 49, "Total current liabilities 1,420 1,590"),
    ("short_term_debt", "2025", 60, "F25", 47, "Short-term borrowings and current maturities of long-term debt 60 62"),
    ("short_term_debt", "2024", 62, "F25", 47, "Short-term borrowings and current maturities of long-term debt 60 62"),
    ("short_term_debt", "2023", 69, "F24", 49, "Short-term borrowings and current maturities of long-term debt 62 69"),
]

# Synthetic LBO inputs. Only the four balance-sheet names are XPO figures; the rest are made-up assumptions.
LBO_INPUTS = [
    ("ebitda", 1272 * M, "normalized EBITDA 2025 (a calculation, not a single fact)"),
    ("entry_multiple", 9.0, "SYNTHETIC assumption"),
    ("exit_multiple", 9.0, "SYNTHETIC assumption"),
    ("leverage", 4.5, "SYNTHETIC assumption, x EBITDA"),
    ("interest_rate", 0.085, "SYNTHETIC assumption"),
    ("tax_rate", 0.25, "SYNTHETIC assumption"),
    ("cash_conversion", 0.6, "SYNTHETIC assumption"),
    ("fees_pct", 0.02, "SYNTHETIC assumption"),
    ("years", 5, "SYNTHETIC assumption"),
    ("current_assets", 1630 * M, "FACT: total current assets 2025"),
    ("cash", 310 * M, "FACT: cash and cash equivalents 2025"),
    ("current_liabilities", 1555 * M, "FACT: total current liabilities 2025"),
    ("short_term_debt", 60 * M, "FACT: short-term borrowings and current maturities 2025"),
]


def synthetic_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws["A1"] = ("SYNTHETIC LBO MODEL. Not XPO's model. Inputs marked FACT are set to XPO's verified 10-K figures; "
                "the rest are made-up assumptions.")
    ws["A3"], ws["B3"], ws["C3"] = "name", "value", "note"
    for i, (name, value, note) in enumerate(LBO_INPUTS, start=4):
        ws[f"A{i}"], ws[f"B{i}"], ws[f"C{i}"] = name, value, note
        wb.defined_names[name] = DefinedName(name, attr_text=f"Inputs!$B${i}")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def multipart_file(field, name, data, ctype):
    b = uuid.uuid4().hex
    head = (f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode()
    return head + data + f"\r\n--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


docs = {"F25": upload("XPO_10-K_FY2025.htm"), "F24": upload("XPO_10-K_FY2024.htm")}
seeded = failed = 0
for metric, period, value, doc_key, page, quote in ROWS:
    body = {"entity": "XPO", "metric": metric, "period": period, "value": str(value * M), "unit": "USD",
            "document_id": docs[doc_key], "page": page, "quote": quote, "scale": str(M)}
    s, d = call("POST", "/facts", body)
    if s != 201:
        failed += 1
        print(f"fact {metric} {period} rejected: {d}")
        continue
    seeded += call("POST", f"/facts/{d['id']}/review", {"action": "accept"})[0] == 200
print(f"xpo facts: {seeded} accepted, {failed} rejected")

s, q = call("POST", "/dd/questions", {"deal": "Project Orchard",
            "question": "What was XPO's total adjusted EBITDA for 2025?"})
if s == 201:
    # An answer is stored with one document, page and quote, and /dd/questions checks the quote on that page.
    s2, _ = call("PATCH", f"/dd/questions/{q['id']}", {
        "answer": "Total adjusted EBITDA was $1,272 million in 2025.",
        "document_id": docs["F25"], "page": 65, "quote": "Total Adjusted EBITDA 1,272 1,266 996"})
    print("dd question answered" if s2 == 200 else f"dd answer rejected: {s2}")

raw, ctype = multipart_file("file", "lbo_model_SYNTHETIC.xlsx", synthetic_workbook(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
s, ties = call("POST", "/lbo/workbook/ties", raw=raw, ctype=ctype)
if s == 200:
    print("lbo ties untied:", ", ".join(ties["untied"]))
else:
    print("lbo ties failed:", s, ties)
