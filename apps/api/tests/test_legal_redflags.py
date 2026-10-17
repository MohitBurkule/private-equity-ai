from app.legal import extract, red_flags

CREDIT = [
    (
        1,
        "The Total Net Leverage Ratio shall not exceed 6.00 to 1.00 as of any quarter end.",
    ),
    (2, "The Maturity Date means June 30, 2031."),
]
SPA = [
    (
        1,
        "Upon a Change of Control of the Company, the Buyer may terminate this Agreement.",
    ),
    (2, "Sellers shall not solicit employees for 36 months."),
]


def test_leverage_and_absent_coverage_flagged_with_cite():
    flags = red_flags(extract(CREDIT, "credit"))
    lev = next(f for f in flags if f["rule"] == "leverage_loose")
    assert (
        lev["value"] == "6.00"
        and lev["page"] == 1
        and lev["quote"].startswith("The Total Net Leverage")
    )
    assert any(
        f["rule"] == "negation_review" for f in flags
    )  # "shall not exceed" needs a human
    assert (
        any(f["rule"] == "coverage_tight" for f in flags) is False
    )  # coverage absent, not a breach


def test_change_of_control_and_long_non_solicit():
    flags = red_flags(extract(SPA, "spa"))
    assert {"coc_present", "non_solicit_long"} <= {f["rule"] for f in flags}
    assert all(f["quote"] for f in flags if f["rule"] != "gov_law_absent")


def test_absent_rule_has_no_cite_and_no_guess():
    flags = red_flags(extract([(1, "Nothing relevant here.")], "nda"))
    gov = next(f for f in flags if f["rule"] == "gov_law_absent")
    assert gov["quote"] is None and gov["value"] is None


def test_word_numbers_parsed_and_long_survival_flagged():
    flags = red_flags(
        extract(
            [(1, "Obligations survive for seven (7) years after termination.")], "nda"
        )
    )
    f = next(x for x in flags if x["rule"] == "survival_long")
    assert f["value"] == "seven (7)" and f["page"] == 1


def test_word_number_without_digits_still_parsed():
    flags = red_flags(
        extract([(1, "Sellers shall not solicit employees for twelve months.")], "nda")
    )
    assert all(f["rule"] != "non_solicit_long" for f in flags)
