import io
import zipfile
from decimal import Decimal
from pathlib import Path

from app.formd import parse_tables, parse_zip, quarter_url, rounds, search

FX = Path(__file__).parent / "fixtures" / "formd"
T = {n: (FX / f"{n}.tsv").read_text() for n in ("FORMDSUBMISSION", "OFFERING", "ISSUERS")}


def test_join_amounts_dates_and_citation_url():
    rs = parse_tables(T["FORMDSUBMISSION"], T["OFFERING"], T["ISSUERS"])
    r = next(x for x in rs if x.accession == "0002017560-24-000001")
    assert (r.issuer, r.offered, r.sold, r.filed) == ("Rhino GP Fund II LLC", Decimal(12000000), Decimal(1160000), "2024-03-29")
    assert r.url == "https://www.sec.gov/Archives/edgar/data/2017560/000201756024000001/"


def test_indefinite_is_none_not_zero():
    rs = parse_tables(T["FORMDSUBMISSION"], T["OFFERING"], T["ISSUERS"])
    fund = next(x for x in rs if x.accession == "0001949646-24-000001")
    assert fund.offered is None and fund.sold == Decimal(925202225)


def test_zip_fetch_and_search():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in T.items():
            z.writestr(f"2024Q1_d/{n}.tsv", t)
    seen = []
    rs = rounds(2024, 1, lambda u: (seen.append(u), buf.getvalue())[1])
    assert seen == [quarter_url(2024, 1)] and len(rs) == len(parse_zip(buf.getvalue()))
    assert [r.issuer for r in search(rs, "rhino gp")] == ["Rhino GP Fund II LLC"] and search(rs, "") == []


def test_test_filings_dropped():
    sub = T["FORMDSUBMISSION"].replace("\tLIVE\t", "\tTEST\t")
    assert parse_tables(sub, T["OFFERING"], T["ISSUERS"]) == []
