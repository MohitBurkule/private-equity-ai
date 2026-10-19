"""UK red flags: each Companies House summary line that should flag does, and clean pages stay quiet."""
from datetime import date

from app.uk_red_flags import red_flags

URL = "https://find-and-update.company-information.service.gov.uk/company/1/charges"


def test_outstanding_charge_flags_with_citation():
    page = "<p>Outstanding / part satisfied</p><p>2 charges registered</p><p>1 outstanding, 1 satisfied, 0 part satisfied</p>"
    flags = red_flags({"charges": (URL, page)})
    assert [f.kind for f in flags] == ["charge"] and flags[0].url == URL
    assert "1 outstanding, 1 satisfied" in flags[0].quote


def test_clean_charges_page_is_quiet():
    page = "<p>0 charges registered</p><p>0 outstanding, 0 satisfied, 0 part satisfied</p>"
    assert red_flags({"charges": (URL, page)}) == []


def test_recent_psc_flags_old_one_does_not():
    psc = "<p>1 person with significant control / 0 statements</p><p>Notified on 20 November 2023</p>"
    assert red_flags({"psc": (URL, psc)}, today=date(2024, 6, 1))[0].kind == "psc"
    assert red_flags({"psc": (URL, psc)}, today=date(2026, 10, 1)) == []


def test_officer_churn_threshold():
    three = "<p>Officers: 4 officers / 3 resignations</p>"
    two = "<p>Officers: 4 officers / 2 resignations</p>"
    assert [f.kind for f in red_flags({"officers": (URL, three)})] == ["officer_churn"]
    assert red_flags({"officers": (URL, two)}) == []
