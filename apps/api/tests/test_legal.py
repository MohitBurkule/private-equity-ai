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
