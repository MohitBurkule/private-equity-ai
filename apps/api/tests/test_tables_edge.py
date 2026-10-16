from decimal import Decimal as D

from app.extract.tables import extract_rows


def vals(text):
    return [r.values for r in extract_rows(text, 1)]


def test_parens_and_minus_are_negative():
    assert vals("Net income (1,234) 2,000") == [(D(-1234), D(2000))]
    assert vals("Loss -45.5 (12.0)") == [(D("-45.5"), D(-12))]


def test_space_grouped_number_is_not_misread():
    assert vals("Revenue 1 000 900") == []  # would otherwise read 1, 0, 900


def test_mixed_scales_on_one_page_abstain():
    assert extract_rows("(in millions)\nRevenue 10\nOther (in thousands)\nCost 5", 1) == []


def test_single_scale_binds():
    assert extract_rows("(in thousands)\nRevenue 1,000 900", 1)[0].scale == D(1000)


def test_unicode_labels_and_dashes_abstain_or_parse_never_guess():
    assert vals("Revenue — 1,000 900") == []
    assert vals("Total ¥ 1,000 900") == []
    assert vals("Résumé café 5") == []
