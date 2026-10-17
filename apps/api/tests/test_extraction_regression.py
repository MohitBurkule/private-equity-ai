"""Extraction accuracy floor for CI. The real golden set (data/golden) is not in the repo, so this
fixed corpus stands in: any change to the row parser that drops or mis-reads one of these tables
fails the build. Add a case whenever a real miss is fixed, so it cannot come back."""

from decimal import Decimal as D

import pytest

from app.extract.tables import extract_rows

# (page text, expected {label: values}) — values are signed and unscaled, as printed.
CORPUS = [
    (
        "(in thousands)\nRevenue 1,000 900\nCost of sales (400) (350)",
        {"revenue": [D(1000), D(900)], "cost of sales": [D(-400), D(-350)]},
    ),
    ("(GBP mm)\nNet income 150 120", {"net income": [D(150), D(120)]}),
    (
        "Operating profit 25\nInterest payable (5)",
        {"operating profit": [D(25)], "interest payable": [D(-5)]},
    ),
    ("(in millions)\nTotal assets 2,300 2,100", {"total assets": [D(2300), D(2100)]}),
]


@pytest.mark.parametrize("text,expected", CORPUS)
def test_corpus_rows_extracted(text, expected):
    got = {r.label.lower(): list(r.values) for r in extract_rows(text, 1)}
    for label, values in expected.items():
        assert got.get(label) == values, f"{label!r} regressed: {got}"
