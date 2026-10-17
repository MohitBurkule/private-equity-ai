from app.legal import extract

P1 = ("This Agreement shall be governed by the laws of the State of New York, without regard to conflicts. "
      "The term of this Agreement is two (2) years.")
NDA = [(1, P1),
       (2, "Obligations survive for five (5) years after termination. Recipient shall not solicit employees for 12 months.")]

CREDIT = [(3, "The Total Net Leverage Ratio shall not exceed 4.50 to 1.00 as of any quarter end."),
          (4, "The Maturity Date means June 30, 2031. Interest at the Applicable Margin of 3.25%.")]


def test_nda_terms_cited_and_absent_listed():
    r = extract(NDA, "nda")
    by = {f["term"]: f for f in r["findings"]}
    assert by["governing_law"]["value"] == "New York" and by["governing_law"]["page"] == 1
    assert by["term_years"]["page"] == 1 and by["confidentiality_survival_years"]["page"] == 2
    assert by["non_solicit_months"]["value"] == "12"
    assert all(f["quote"] for f in r["findings"])


def test_credit_terms_and_no_guessing():
    r = extract(CREDIT, "credit")
    by = {f["term"]: f for f in r["findings"]}
    assert by["max_leverage"]["value"] == "4.50" and by["maturity"]["value"] == "June 30, 2031"
    assert by["margin"]["value"] == "3.25%"
    assert "min_interest_coverage" in r["absent"]


def test_negation_flagged_and_bad_type():
    r = extract([(1, "There is no non-compete restriction of 24 months on the sellers.")], "spa")
    f = next(x for x in r["findings"] if x["term"] == "non_compete_months")
    assert f["needs_review"] is True
    try:
        extract([], "lease")
        raise AssertionError
    except ValueError:
        pass


def test_termination_fee_amount_is_read_from_the_definition():
    out = extract([(7, "“Company Termination Fee” means $12,500,000.")], "spa")
    assert [(f["term"], f["value"]) for f in out["findings"] if f["term"] == "termination_fee"] == [
        ("termination_fee", "$12,500,000")]


def test_governing_law_reads_governed_in_all_respects_by():
    out = extract([(5, "5. Governing Law. This Amendment shall be governed in all respects by the laws of the State of Delaware.")], "spa")
    assert [f["value"] for f in out["findings"] if f["term"] == "governing_law"] == ["Delaware"]


def test_governing_law_reads_through_a_parenthetical_after_laws():
    out = extract([(9, "This Agreement shall be governed by, and construed in accordance with, the Laws (excluding conflict of laws rules and principles) of the State of Delaware.")], "spa")
    assert [f["value"] for f in out["findings"] if f["term"] == "governing_law"] == ["Delaware"]


def test_non_solicit_years_become_months_and_may_come_first():
    out = extract([(3, "Seller shall not, for a period of four (4) years after the Closing Date, directly or indirectly solicit any employee.")], "spa")
    assert [f["value"] for f in out["findings"] if f["term"] == "non_solicit_months"] == ["48"]


def test_termination_fee_is_not_read_from_an_expense_cap():
    out = extract([(34, "fees and expenses shall not exceed $6,500,000 in the aggregate, the Termination Fee payable by Parent.")], "spa")
    assert [f for f in out["findings"] if f["term"] == "termination_fee"] == []


def test_governing_law_reads_governed_and_interpreted_under_laws():
    out = extract([(7, "This Agreement shall be governed and interpreted under the Laws of the State of New York.")], "nda")
    assert [f["value"] for f in out["findings"] if f["term"] == "governing_law"] == ["New York"]


def test_non_solicit_second_anniversary_is_24_months():
    out = extract([(4, "Buyer shall not solicit any employee until the second (2nd) anniversary of the Closing Date.")], "spa")
    assert [f["value"] for f in out["findings"] if f["term"] == "non_solicit_months"] == ["24"]
