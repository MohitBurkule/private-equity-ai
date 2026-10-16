from decimal import Decimal
from pathlib import Path

import pytest

from app import fred, gleif

FX = Path(__file__).parent / "fixtures" / "open"


def test_gleif_parse_real_response_and_search_url():
    es = gleif.parse(__import__("json").loads((FX / "gleif.json").read_text()))
    e = es[0]
    assert (e.lei, e.name, e.country, e.status) == ("5299004LW4QWGZUB8Y96", "BLACKSTONE INC.", "US", "ACTIVE")
    assert e.url.endswith("/5299004LW4QWGZUB8Y96")
    seen = []
    gleif.search("Blackstone Inc", 2, lambda u: (seen.append(u), (FX / "gleif.json").read_bytes())[1])
    assert "filter%5Bentity.legalName%5D=Blackstone+Inc" in seen[0]


def test_fred_skips_missing_and_cites_series():
    text = (FX / "fred.csv").read_text() + "2026-10-16,.\n"
    assert fred.parse(text)[-1] == ("2026-10-15", Decimal("5.10"))
    d, v, url = fred.latest("DGS10", lambda u: text.encode())
    assert (d, v, url) == ("2026-10-15", Decimal("5.10"), "https://fred.stlouisfed.org/series/DGS10")


def test_fred_empty_raises():
    with pytest.raises(LookupError):
        fred.latest("X", lambda u: b"observation_date,X\n")


def test_dealscan_leads_cite_filing():
    from app import dealscan
    seen = []
    ls = dealscan.scan("2026-09-01", "2026-10-15", fetch=lambda u: (seen.append(u), (FX / "efts_merger.json").read_bytes())[1])
    assert len(ls) == 5 and all(x.url.startswith("https://www.sec.gov/Archives/edgar/data/") for x in ls)
    assert all(x.accession.replace("-", "") in x.url and x.form for x in ls)
    assert "startdt=2026-09-01" in seen[0] and "%22agreement+and+plan+of+merger%22" in seen[0]
