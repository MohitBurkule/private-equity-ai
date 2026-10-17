from decimal import Decimal

from app.memo import derive_lines, risk_lines


def test_margins_fcf_growth_cite_their_inputs():
    facts = {
        ("revenue", "FY2024"): (Decimal(100), "USD", 1), ("revenue", "FY2025"): (Decimal(120), "USD", 2),
        ("gross_profit", "FY2025"): (Decimal(60), "USD", 3),
        ("operating_cash_flow", "FY2025"): (Decimal(30), "USD", 4), ("capex", "FY2025"): (Decimal(-10), "USD", 5),
    }
    lines = derive_lines(facts)
    assert "gross margin (FY2025): 50.00% = gross_profit [3] / revenue [2]" in lines
    assert "free cash flow (FY2025): 20.00 USD = operating_cash_flow [4] - capex [5]" in lines
    assert "revenue growth (FY2025 vs FY2024): 20.00% = revenue [2] vs revenue [1]" in lines


def test_no_derivation_across_units():
    facts = {("revenue", "FY2024"): (Decimal(100), "USD", 1), ("net_income", "FY2024"): (Decimal(5), "EUR", 2)}
    assert not [x for x in derive_lines(facts) if x.startswith("net margin")]


def test_risks_only_from_cited_negatives_and_declines():
    facts = {
        ("net_income", "FY2024"): (Decimal(-6), "USD", 3),
        ("revenue", "FY2024"): (Decimal(100), "USD", 1), ("revenue", "FY2025"): (Decimal(90), "USD", 2),
        ("operating_cash_flow", "FY2025"): (Decimal(5), "USD", 4), ("capex", "FY2025"): (Decimal(-9), "USD", 5),
    }
    r = risk_lines(facts)
    assert "net income negative in FY2024 (-6.00) [3]" in r
    assert "revenue fell in FY2025 vs FY2024 [2, 1]" in r
    assert "free cash flow negative in FY2025 [4, 5]" in r


def test_net_debt_is_debt_less_cash_and_cites_both_components():
    from app.derived import net_debt_points
    from app.memo import ratio_series

    facts = {
        ("long_term_debt", "FY2025"): (Decimal(3253), "USD", 7), ("cash", "FY2025"): (Decimal(310), "USD", 8),
        ("long_term_debt", "FY2024"): (Decimal(3325), "USD", 9),  # no FY2024 cash: no net debt for that year
        ("ebitda", "FY2025"): (Decimal(1142), "USD", 10),
    }
    nd = net_debt_points(facts)
    assert nd == {"FY2025": (Decimal(2943), "USD", (7, 8))}
    ratios = ratio_series({**facts, **{("net_debt", p): x for p, x in nd.items()}})
    (period, _, notes), = ratios["net debt / EBITDA"]
    assert period == "FY2025" and notes == (7, 8, 10)


def test_net_debt_not_formed_across_units():
    from app.derived import net_debt_points

    facts = {("long_term_debt", "FY2025"): (Decimal(3), "USD", 1), ("cash", "FY2025"): (Decimal(1), "EUR", 2)}
    assert net_debt_points(facts) == {}
