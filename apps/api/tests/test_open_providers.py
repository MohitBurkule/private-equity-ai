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


def test_news_items_and_filter_and_entity_rejection():
    from app import newsfeed
    blob = (FX / "bbc_rss.xml").read_bytes()
    items = newsfeed.parse("bbc_business", blob)
    assert len(items) == 3 and all(i.link.startswith("https://") and i.published for i in items)
    assert newsfeed.headlines("bbc_business", "zzzz-none", lambda u: blob) == []
    with pytest.raises(ValueError):
        newsfeed.parse("x", b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "b">]><rss/>')
    with pytest.raises(KeyError):
        newsfeed.headlines("nope")


def test_wikidata_hits():
    import json

    from app import wikidata
    hs = wikidata.parse(json.loads((FX / "wikidata_search.json").read_text()))
    assert hs[0].qid == "Q880942" and hs[0].label == "Blackstone Inc." and hs[0].url.endswith("/Q880942")


def test_form13f_managers_holdings_and_citation():
    from app import form13f
    d = FX / "f13"
    ms = form13f.parse_managers((d / "SUBMISSION.tsv").read_text(), (d / "COVERPAGE.tsv").read_text())
    hit = form13f.find_managers(ms, "blackstone inc")
    assert [m.accession for m in hit] == ["0001193125-26-352211"] and hit[0].period == "2026-06-30"
    assert len(form13f.find_managers(ms, "blackstone inc", latest_only=False)) == 2
    hs = form13f.parse_holdings((d / "INFOTABLE.tsv").open(newline=""), hit[0].accession, hit[0].cik)
    assert len(hs) == 6
    c = next(h for h in hs if h.issuer == "CIENA CORP")
    assert (c.value_usd, c.shares, c.cusip) == (Decimal(4030932), Decimal(8217), "171779309")
    assert c.url == "https://www.sec.gov/Archives/edgar/data/1393818/000119312526352211/"
    assert form13f.top(hs, 1)[0].value_usd == max(h.value_usd for h in hs)


def test_form13f_zip_roundtrip(tmp_path):
    import zipfile

    from app import form13f
    d = FX / "f13"
    p = tmp_path / "q.zip"
    with zipfile.ZipFile(p, "w") as z:
        for n in ("SUBMISSION", "COVERPAGE", "INFOTABLE"):
            z.write(d / f"{n}.tsv", f"{n}.tsv")
    m = form13f.find_managers(form13f.managers_from_zip(p), "Blackstone Inc")[0]
    assert len(form13f.holdings_from_zip(p, m)) > 0


def test_adv_roster_parse_search_and_urls():
    from app import adv
    rows = adv.parse((FX / "adv_roster.csv").read_text())
    a = adv.search(rows, "apollo capital")[0]
    assert (a.crd, a.pe_funds, a.private_funds, a.private_fund_gross_assets_usd) == ("143161", 214, 711, Decimal("405948410054.00"))
    assert a.url == "https://adviserinfo.sec.gov/firm/summary/143161" and adv.search(rows, "") == []
