from decimal import Decimal

import pytest

from app import marketdata as md



def test_latest_wins_and_case_normalised():
    p = md.CsvProvider("symbol,price,currency,as_of\nabc,10.5,usd,2024-01-02\nABC,11.0,USD,2024-01-03\n")
    q = p.quote("abc")
    assert q.price == Decimal("11.0") and q.currency == "USD" and q.source == "csv"


def test_missing_symbol_is_no_data_not_zero():
    p = md.CsvProvider("symbol,price,currency,as_of\nA,1,USD,2024-01-01\n")
    with pytest.raises(md.NoData):
        p.quote("B")


@pytest.mark.parametrize("text", ["a,b\n1,2\n", "symbol,price,currency,as_of\nA,x,USD,2024-01-01\n",
                                  "symbol,price,currency,as_of\nA,-1,USD,2024-01-01\n",
                                  "symbol,price,currency,as_of\nA,1,,2024-01-01\n"])
def test_bad_csv_rejected(text):
    with pytest.raises(ValueError):
        md.CsvProvider(text)


def test_registry():
    md.register(md.CsvProvider("symbol,price,currency,as_of\nA,1,USD,2024-01-01\n", name="t"))
    assert md.get("t").quote("A").price == 1
    with pytest.raises(md.NoData):
        md.get("nope")
