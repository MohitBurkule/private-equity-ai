"""SEC Form 13F holdings from the SEC's quarterly 13F data set (public domain, free).

Open stand-in for the public-equity side of ownership data (FactSet/CapIQ ownership). Limits that matter: long US-listed
positions only, filed up to 45 days after quarter end, confidential positions omitted, amendments restate earlier filings.
VALUE is whole US dollars in this data set (2023 onward). Every row cites its filing's EDGAR index URL.
The full INFOTABLE is hundreds of MB, so `holdings` streams the file and keeps only the wanted accession.
"""
from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Manager:
    accession: str
    cik: str
    name: str
    form: str
    filed: str
    period: str
    url: str


@dataclass(frozen=True)
class Holding:
    accession: str
    issuer: str
    title_of_class: str
    cusip: str
    value_usd: Decimal | None
    shares: Decimal | None
    share_type: str
    put_call: str
    url: str


def _d(v: str) -> str:
    try:
        return datetime.strptime(v.strip().title(), "%d-%b-%Y").replace(tzinfo=UTC).date().isoformat()
    except ValueError:
        return v.strip()


def _n(v: str) -> Decimal | None:
    try:
        x = Decimal(v.strip())
    except (InvalidOperation, AttributeError):
        return None
    return x if x.is_finite() and x >= 0 else None


def _url(cik: str, acc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"


def _tsv(text) -> Iterator[dict[str, str]]:
    return csv.DictReader(text, delimiter="\t")


def parse_managers(submission: str, coverpage: str) -> list[Manager]:
    names = {r["ACCESSION_NUMBER"]: r["FILINGMANAGER_NAME"].strip() for r in _tsv(io.StringIO(coverpage))}
    return [Manager(r["ACCESSION_NUMBER"], r["CIK"], names.get(r["ACCESSION_NUMBER"], ""), r["SUBMISSIONTYPE"],
                    _d(r["FILING_DATE"]), _d(r["PERIODOFREPORT"]), _url(r["CIK"], r["ACCESSION_NUMBER"]))
            for r in _tsv(io.StringIO(submission))]


def find_managers(ms: list[Manager], name: str, latest_only: bool = True) -> list[Manager]:
    n = name.strip().lower()
    hits = [m for m in ms if n and n in m.name.lower()]
    if latest_only and hits:
        top = max(m.period for m in hits)
        hits = [m for m in hits if m.period == top]
    return hits


def parse_holdings(infotable, accession: str, cik: str) -> list[Holding]:
    out = []
    for r in _tsv(infotable):
        if r["ACCESSION_NUMBER"] != accession:
            continue
        out.append(Holding(accession, r["NAMEOFISSUER"].strip(), r["TITLEOFCLASS"].strip(), r["CUSIP"].strip(),
                           _n(r["VALUE"]), _n(r["SSHPRNAMT"]), r["SSHPRNAMTTYPE"].strip(), r["PUTCALL"].strip(),
                           _url(cik, accession)))
    return out


def managers_from_zip(path_or_file) -> list[Manager]:
    with zipfile.ZipFile(path_or_file) as z:
        return parse_managers(z.read("SUBMISSION.tsv").decode("utf-8", "replace"),
                              z.read("COVERPAGE.tsv").decode("utf-8", "replace"))


def holdings_from_zip(path_or_file, manager: Manager) -> list[Holding]:
    with zipfile.ZipFile(path_or_file) as z, z.open("INFOTABLE.tsv") as raw:
        return parse_holdings(io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline=""),
                              manager.accession, manager.cik)


def top(hs: list[Holding], n: int = 10) -> list[Holding]:
    return sorted((h for h in hs if h.value_usd is not None), key=lambda h: h.value_usd, reverse=True)[:n]
