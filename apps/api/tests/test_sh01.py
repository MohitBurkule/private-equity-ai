"""Page text of Monzo Bank Ltd SH01 received 02/09/2025 (Companies House, public), as extracted from the PDF."""
import hashlib

from app.parse.sh01 import parse_capital_form

P1 = """                                                    SH01(ef)

                                                    Return of Allotment of Shares

Company Name:         Monzo Bank Limited
Company Number:       09446231

Received for filing in Electronic Format on the: 02/09/2025        XEA7OC5E

Shares Allotted (including bonus shares)

Date or period during which                      From                          To
shares are allotted                           15/08/2025                  15/08/2025

Class of Shares:      ORDINARY                      Number allotted                   15000000
Currency:             GBP                           Nominal value of each share       0.001
                                                    Amount paid:                      1
                                                    Amount unpaid:                    0
No shares allotted other than for cash
"""
P2 = """Statement of Capital (Share Capital)

Class of Shares:      ORDINARY                      Number allotted                  41807801
Currency:             GBP                           Aggregate nominal value:         41807.801
"""
P3 = """Statement of Capital (Totals)

Currency:                  GBP                            Total number of shares:                 41807801
                                                          Total aggregate nominal value:          41807.801
"""


def test_monzo_sh01_values_carry_page_and_quote():
    f = parse_capital_form([(1, P1, False), (2, P2, False), (3, P3, False)])
    assert f.form == "SH01" and f.company_number.value == "09446231"
    assert (f.date_from.value, f.date_to.value) == ("15/08/2025", "15/08/2025")
    a = f.allotments[0]
    assert a.cls.value == "ORDINARY" and a.number.value == 15000000 and a.number.page == 1
    assert "Number allotted" in a.number.quote and a.number.quote in P1
    assert str(a.nominal.value) == "0.001" and a.paid.value == 1 and a.unpaid.value == 0
    assert f.total_shares.value == 41807801 and f.total_shares.page == 3 and f.total_shares.quote in P3
    assert f.statement_rows[0].number.value == 41807801 and not f.problems


def test_ocr_confusions_are_reported_not_repaired():
    bad = P1.replace("15000000", "l5OOOOOO")
    f = parse_capital_form([(1, bad, True), (3, P3, True)])
    assert f.allotments[0].number.readable is False and f.allotments[0].number.value == "l5OOOOOO"
    assert f.allotments[0].number.ocr is True
    assert any("unreadable" in p for p in f.problems)


def test_class_rows_not_adding_to_the_printed_total_is_a_problem():
    f = parse_capital_form([(1, P1, False), (2, P2.replace("41807801", "41807800"), False), (3, P3, False)])
    assert any("add to 41807800" in p for p in f.problems)


def test_no_form_type_is_a_problem_not_a_guess():
    f = parse_capital_form([(1, "just some text", False)])
    assert f.form is None and "form type not found" in f.problems[0]


OCR_FORM_B = """Companies House  SH01  (ef)
Return of Allotment of Shares
Company Name:  Monzo Bank Limited
Company Number:09446231
Received for filing in Electronic Format on the: 20/03/2025  XDYP9NMX
Shares Allotted (including bonus shares)
Date or period during which  From
shares are allotted  12/03/2025  12/03/2025
Class of Shares:  ORDINARY  Number allotted  15519568
Currency:  GBP  Nominal value of each share  0.001
Amount paid:  7.41
Amount unpaid:  0.0
Noshares allotted otherthanfor cash
Electronically filed document for Company Number:  09446231  Page: 1
"""


def test_ocr_text_feeds_the_share_ledger_for_the_same_day_forms():
    """Monzo SH01 filed 21/03/2025 (read by OCR) plus the form filed 20/03/2025 (golden s02): 26,807,801."""
    from decimal import Decimal as D

    from app.shareledger import Event, reconcile
    b = parse_capital_form([(1, OCR_FORM_B, True), (2, "Statement of Capital (Totals)\nTotal number of shares:  26753982\n", True)])
    assert b.allotments[0].number.value == 15519568 and b.allotments[0].number.ocr and b.allotments[0].paid.value == D("7.41")
    led = reconcile(D(11234414), "SH01 2025-02-04", [
        Event("allot", "2025-03-12", "SH01 filed 20/03/2025", D(53819), D(11288233)),
        Event("allot", "2025-03-12", "SH01 filed 21/03/2025", b.allotments[0].number.value, b.total_shares.value)])
    assert led.running == D(26807801) and not led.problems


def test_endpoint_returns_citations_and_hides_other_tenants():
    from fastapi.testclient import TestClient

    from app.main import SessionLocal, app
    from app.models import Document, PageRow
    from tests.helpers import new_tenant
    c = TestClient(app)
    t = c.post("/admin/tenants", json={"name": "shx"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    # Document ids are a global primary key, so derive one per tenant rather than reuse a fixed id.
    doc_id = hashlib.sha256(f"sh01:{t['tenant_id']}".encode()).hexdigest()
    with SessionLocal() as db:
        from app.rls import bind_tenant
        bind_tenant(db, t["tenant_id"])
        d = Document(id=doc_id, tenant_id=t["tenant_id"], sha256="x", filename="sh01.pdf", n_pages=2)
        d.pages = [PageRow(number=1, text=P1, method="ocr", ocr_confidence=0.85), PageRow(number=2, text=P2, method="ocr")]
        db.add(d)
        db.commit()
    r = c.get(f"/documents/{doc_id}/capital-form", headers=h).json()
    assert r["form"] == "SH01" and r["allotments"][0]["number"]["value"] == "15000000"
    assert r["allotments"][0]["number"]["ocr"] is True and r["allotments"][0]["number"]["page"] == 1
    assert c.get(f"/documents/{doc_id}/capital-form", headers=new_tenant(c, "shy")).status_code == 404
