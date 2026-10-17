import io

from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app import outbound
from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def xlsx_bytes(cells: list[str], number: float) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i, text in enumerate(cells, start=1):
        ws.cell(row=i, column=1, value=text)
    ws.cell(row=len(cells) + 1, column=1, value=number)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_pii_flag_is_admin_only_and_audited():
    t = c.post("/admin/tenants", json={"name": "pii-flag"}, headers=ADMIN).json()
    assert c.put(f"/admin/tenants/{t['tenant_id']}/pii-redaction", json={"on": True}).status_code == 403
    assert c.put(f"/admin/tenants/{t['tenant_id']}/pii-redaction", json={"on": "yes"}, headers=ADMIN).status_code == 422
    r = c.put(f"/admin/tenants/{t['tenant_id']}/pii-redaction", json={"on": True}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["pii_redaction"] is True


def test_text_is_redacted_only_when_on():
    assert outbound.text(False, "mail ana@fund.com") == "mail ana@fund.com"
    assert "ana@fund.com" not in outbound.text(True, "mail ana@fund.com")


def test_xlsx_scrubs_text_cells_and_keeps_numbers():
    out = load_workbook(io.BytesIO(outbound.xlsx(xlsx_bytes(["ana@fund.com"], 1234.5))))
    ws = out.active
    assert ws["A1"].value != "ana@fund.com" and "@" not in ws["A1"].value
    assert ws["A2"].value == 1234.5


def test_docx_scrubs_a_paragraph_split_across_runs():
    d = Document()
    p = d.add_paragraph()
    p.add_run("Call ana ")
    p.add_run("ana@fund.com")
    p.add_run(" today")
    b = io.BytesIO()
    d.save(b)
    out = Document(io.BytesIO(outbound.docx(b.getvalue())))
    text = out.paragraphs[0].text
    assert "@" not in text and "Call ana" in text


def test_document_reads_are_in_the_audit_trail():
    t = c.post("/admin/tenants", json={"name": "doc-read"}, headers=ADMIN).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    files = {"file": ("reads.xlsx", xlsx_bytes(["Revenue"], 10), "x")}
    doc_id = c.post("/documents", files=files, data={"deal": "Reads"}, headers=h).json()["id"]
    c.get(f"/documents/{doc_id}/pages/1", headers=h)
    rows = c.get("/audit", params={"action": "document.read"}, headers=h).json()["items"]
    assert any(r["payload"]["doc_id"] == doc_id for r in rows)
