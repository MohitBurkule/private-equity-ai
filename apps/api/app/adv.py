"""SEC investment-adviser roster (Form ADV FOIA data): who runs private funds and how big, free and public domain.

Open stand-in for the manager-profile side of Preqin/PitchBook. Figures are self-reported on Form ADV and rounded by
the filer; a firm can file under several registered entities (umbrella filings), so search by name and compare rows.
Each Adviser links its adviserinfo.sec.gov page for citation. Source: SEC "Information About Registered Investment
Advisers and Exempt Reporting Advisers" (monthly zip, one CSV).
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Adviser:
    crd: str
    sec_number: str
    name: str
    firm_type: str
    city: str
    state: str
    country: str
    status: str
    latest_adv_filing: str
    pe_funds: int | None
    private_funds: int | None
    private_fund_gross_assets_usd: Decimal | None
    url: str


def _int(v: str) -> int | None:
    v = (v or "").replace(",", "").strip()
    return int(v) if v.isdigit() else None


def _usd(v: str) -> Decimal | None:
    try:
        d = Decimal((v or "").replace(",", "").strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() and d >= 0 else None


def parse(text: str) -> list[Adviser]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        crd = r["Organization CRD#"].strip()
        out.append(Adviser(crd, r["SEC#"].strip(), r["Primary Business Name"].strip(), r["Firm Type"].strip(),
                           r["Main Office City"].strip(), r["Main Office State"].strip(),
                           r["Main Office Country"].strip(), r["SEC Current Status"].strip(),
                           r["Latest ADV Filing Date"].strip(), _int(r["Total number of PE funds"]),
                           _int(r["Count of Private Funds - 7B(1)"]), _usd(r["Total Gross Assets of Private Funds"]),
                           f"https://adviserinfo.sec.gov/firm/summary/{crd}"))
    return out


def parse_zip(path_or_file) -> list[Adviser]:
    import zipfile
    with zipfile.ZipFile(path_or_file) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return parse(z.read(name).decode("latin-1"))


def search(advisers: list[Adviser], name: str) -> list[Adviser]:
    n = name.strip().lower()
    return [a for a in advisers if n and n in a.name.lower()]
