"""Capital-call notice (PDF) → cited fact. The notice is SYNTHETIC and generated here with reportlab, so no binary
sits in the repo. It goes through the normal PDF ingest, then the label reader in app/fundadmin.py."""
import io

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app import fundadmin
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
LINES = [
    "Capital Call Notice (SYNTHETIC)",
    "Fund: Fund VII (SYNTHETIC)",
    "Limited Partner: LP Alpha (SYNTHETIC)",
    "Call amount: USD 12,500,000",
    "Due date: 2026-10-31",
    "Purpose: Investment in Acme Holdings (SYNTHETIC)",
    "Wire: SYNTHETIC account, reference FVII-CALL-4",
]


def _notice() -> bytes:
    b = io.BytesIO()
    pdf = canvas.Canvas(b)
    for i, line in enumerate(LINES):
        pdf.drawString(72, 740 - 18 * i, line)
    pdf.save()
    return b.getvalue()


def test_label_reader_takes_amount_and_due_date_from_one_page():
    (found,) = fundadmin.extract_notice([(1, "\n".join(LINES))])
    assert (found.metric, found.period, found.value, found.page) == ("capital_call_usd", "2026-10-31", "12500000", 1)
    assert found.quote == "Call amount: USD 12,500,000"


def test_notice_pdf_becomes_a_cited_capital_call_fact():
    h = new_tenant(c, "notice")
    doc = c.post("/documents", files={"file": ("fund7-call4.pdf", _notice(), "application/pdf")}, headers=h).json()["id"]
    r = c.post(f"/documents/{doc}/fund-admin/facts", params={"entity": "Fund VII (SYNTHETIC)"}, headers=h)
    assert r.status_code == 201, r.text
    assert len(r.json()["created"]) == 1 and r.json()["skipped"] == []
