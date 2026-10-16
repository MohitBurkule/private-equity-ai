"""SEC Form D private-placement rounds from the SEC's quarterly Form D data set (free, public domain).

This is the open stand-in for PitchBook/Crunchbase funding-round data, with caveats: amounts are what the issuer
self-reported, "Indefinite" is common and is kept as None (never zero), and the filing says nothing about valuation.
Every Round carries its EDGAR index URL so downstream facts can cite it.
Source: https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets (zip per quarter, TSV inside).
"""
from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Round:
    accession: str
    issuer: str
    cik: str
    state: str
    entity_type: str
    industry: str
    filed: str
    first_sale: str
    offered: Decimal | None
    sold: Decimal | None
    amendment: bool
    url: str


def _amt(v: str) -> Decimal | None:
    try:
        d = Decimal(v.strip())
    except (InvalidOperation, AttributeError):
        return None
    return d if d.is_finite() and d >= 0 else None


def _date(v: str) -> str:
    try:
        return datetime.strptime(v.strip().title(), "%d-%b-%Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return v.strip()


def _tsv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def parse_tables(submission: str, offering: str, issuers: str) -> list[Round]:
    """Join the three TSVs on ACCESSIONNUMBER. Primary issuer only; test filings dropped."""
    subs = {r["ACCESSIONNUMBER"]: r for r in _tsv(submission) if r.get("TESTORLIVE", "LIVE").strip() == "LIVE"}
    offs = {r["ACCESSIONNUMBER"]: r for r in _tsv(offering)}
    out = []
    for i in _tsv(issuers):
        acc = i["ACCESSIONNUMBER"]
        if acc not in subs or acc not in offs or i.get("IS_PRIMARYISSUER_FLAG", "").upper() != "YES":
            continue
        o = offs[acc]
        cik = i["CIK"].strip()
        out.append(Round(acc, i["ENTITYNAME"].strip(), cik, i["STATEORCOUNTRY"].strip(), i["ENTITYTYPE"].strip(),
                         o["INDUSTRYGROUPTYPE"].strip(), _date(subs[acc]["FILING_DATE"]), o["SALE_DATE"].strip(),
                         _amt(o["TOTALOFFERINGAMOUNT"]), _amt(o["TOTALAMOUNTSOLD"]),
                         o["ISAMENDMENT"].strip().lower() == "true",
                         f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"))
    return out


def parse_zip(blob: bytes) -> list[Round]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        def rd(name: str) -> str:
            real = next(n for n in z.namelist() if n.upper().endswith(name))
            return z.read(real).decode("utf-8", "replace")
        return parse_tables(rd("FORMDSUBMISSION.TSV"), rd("OFFERING.TSV"), rd("ISSUERS.TSV"))


def quarter_url(year: int, quarter: int) -> str:
    return f"https://www.sec.gov/files/structureddata/data/form-d-data-sets/{year}q{quarter}_d.zip"


def default_fetch(url: str) -> bytes:
    from app.secfeed import default_fetch as sec
    return sec(url)


def rounds(year: int, quarter: int, fetch: Fetch = default_fetch) -> list[Round]:
    return parse_zip(fetch(quarter_url(year, quarter)))


def search(rs: list[Round], name: str) -> list[Round]:
    n = name.strip().lower()
    return [r for r in rs if n and n in r.issuer.lower()]
