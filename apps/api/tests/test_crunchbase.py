from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.crunchbase import read_funding_rounds

FIXTURE = Path(__file__).parent / "fixtures" / "open" / "crunchbase_funding_rounds_sample.csv"


def test_sample_row_count():
    assert len(read_funding_rounds(FIXTURE)) == 50


def test_first_row_maps_to_schema():
    first = read_funding_rounds(FIXTURE)[0]
    assert first.company == "Imperial Europe Srl"
    assert first.round_type == "grant"
    assert first.announced == date(2015, 5, 1)
    assert first.raised_usd == Decimal("55997.0")
    assert first.post_money_usd is None
    assert first.investors == 1


def test_non_numeric_amount_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "org_name,investment_type,announced_on,raised_amount_usd,post_money_valuation_usd,investor_count\n"
        "X,seed,2020-01-01,abc,,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        read_funding_rounds(bad)
