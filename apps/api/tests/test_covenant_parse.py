from app.covenant_parse import extract

TEXT = [
    (
        10,
        (
            "7.12. Financial Covenants. (a) Prior to the occurrence of a Fall-Away Event, Borrower shall not permit the "
            "Consolidated Secured Net Leverage Ratio to be greater than 3.00:1.00 on and as of the last day of any Fiscal "
            "Quarter; provided that a Qualifying Acquisition steps the maximum up to 3.50:1.00."
        ),
    ),
    (
        11,
        (
            "(b) On and after the occurrence of a Fall-Away Event, Borrower shall not permit the Consolidated Total Net "
            "Leverage Ratio to be greater than 4.00:1.00 on and as of the last day of any Fiscal Quarter."
        ),
    ),
    (
        11,
        (
            "(c) Borrower shall not permit the Interest Coverage Ratio to be less than 2.00:1.00 on and as of the last "
            "day of any Fiscal Quarter."
        ),
    ),
    (12, "Borrower shall not incur debt if the leverage ratio exceeds 2.00 to 1.00."),
]


def test_three_tests_with_section_page_quote_and_direction():
    t = {x["kpi_metric"]: x for x in extract(TEXT)}
    assert (
        t["secured_net_leverage"]["operator"] == "<="
        and t["secured_net_leverage"]["threshold"] == "3.00"
    )
    assert (
        t["secured_net_leverage"]["section"] == "7.12"
        and t["secured_net_leverage"]["page"] == 10
    )
    assert t["total_net_leverage"]["threshold"] == "4.00"
    assert (
        t["interest_coverage"]["operator"] == ">="
        and t["interest_coverage"]["threshold"] == "2.00"
    )


def test_conditions_listed_not_applied_and_unnamed_ratio_skipped():
    t = {x["kpi_metric"]: x for x in extract(TEXT)}
    assert "Fall-Away Event" in t["secured_net_leverage"]["conditions"]
    assert "Qualifying Acquisition" in t["secured_net_leverage"]["conditions"]
    assert (
        t["secured_net_leverage"]["threshold"] == "3.00"
    )  # the 3.50 step-up is text only
    assert (
        len(extract(TEXT)) == 3
    )  # the generic "leverage ratio ... 2.00 to 1.00" debt test is not a covenant


def test_check_flags_breach_with_both_quotes_and_never_guesses_missing_kpi():
    from app.covenant_parse import check

    tests = extract(TEXT)
    observed = {
        "secured_net_leverage": {
            "value": "3.42",
            "period": "FY2026Q2",
            "source": "xpo-q2.htm p.4",
        },
        "interest_coverage": {
            "value": "2.60",
            "period": "FY2026Q2",
            "source": "xpo-q2.htm p.5",
        },
    }
    rows = {r["kpi_metric"]: r for r in check(tests, observed)}
    assert rows["secured_net_leverage"]["status"] == "breach"  # 3.42 > 3.00
    assert (
        rows["secured_net_leverage"]["covenant_quote"].startswith("7.12.")
        or "Secured Net Leverage" in rows["secured_net_leverage"]["covenant_quote"]
    )
    assert rows["interest_coverage"]["status"] == "ok"
    assert rows["total_net_leverage"]["status"] == "not_tested"
