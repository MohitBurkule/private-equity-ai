"""Companies House ownership, officers and company data: parsers for the free bulk products and the REST API.

Formats follow the Companies House PSC snapshot (JSON lines, `{"company_number", "data": {...}}`), the
Basic Company Data CSV (CompanyNumber, CompanyName, ...) and the REST API items. They are ported in
spirit from the user's own project (MohitBurkule/companyhousev1), minus its defaults: a missing status,
category or notification date stays missing here (None); nothing is filled in. Every record keeps its
source line so it can be cited. Test fixtures are SYNTHETIC, shaped from the published formats.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date

_KINDS = {
    "individual-person-with-significant-control": "individual",
    "corporate-entity-person-with-significant-control": "corporate",
    "legal-person-person-with-significant-control": "legal-person",
    "super-secure-person-with-significant-control": "super-secure",
}


@dataclass
class Psc:
    company_number: str
    kind: str  # individual | corporate | legal-person | super-secure | unknown:<raw>
    name: str | None
    natures_of_control: list[str]
    notified_on: str | None
    ceased_on: str | None
    nationality: str | None
    country_of_residence: str | None
    registration_number: str | None  # for corporate owners, their own company number
    legal_form: str | None
    sanctioned: bool | None
    birth_year_month: str | None
    source_line: int | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.ceased_on is None


def _iso(s) -> str | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError:
        return None


def parse_psc_data(number: str, data: dict, line: int | None = None) -> Psc:
    """One PSC entry (snapshot `data` object, or an API item)."""
    raw_kind = data.get("kind") or ""
    ident = data.get("identification") or {}
    dob = data.get("date_of_birth") or {}
    problems = []
    if raw_kind not in _KINDS:
        problems.append(f"unrecognised kind {raw_kind!r}")
    for k in ("notified_on", "ceased_on"):
        if data.get(k) and _iso(data[k]) is None:
            problems.append(f"{k} is not a date: {data[k]!r}")
    ym = f"{dob['year']}-{int(dob['month']):02d}" if dob.get("year") and dob.get("month") else None
    return Psc(number, _KINDS.get(raw_kind, f"unknown:{raw_kind}"), data.get("name"),
               list(data.get("natures_of_control") or []), _iso(data.get("notified_on")),
               _iso(data.get("ceased_on")), data.get("nationality"), data.get("country_of_residence"),
               ident.get("registration_number"), ident.get("legal_form"), data.get("is_sanctioned"), ym,
               line, problems)


def iter_psc_snapshot(lines: Iterable[str | bytes], only: set[str] | None = None) -> Iterator[Psc | dict]:
    """Stream a PSC snapshot. Yields Psc records, or {"line", "error"} for lines that cannot be read.
    `only` keeps just those (already normalised) company numbers, which is how a multi-GB file is used."""
    for n, line in enumerate(lines, 1):
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            yield {"line": n, "error": "not JSON"}
            continue
        num = str(doc.get("company_number") or "").strip().upper()
        if not num or not isinstance(doc.get("data"), dict):
            yield {"line": n, "error": "no company_number or data"}
            continue
        if only is not None and num not in only:
            continue
        yield parse_psc_data(num, doc["data"], n)


@dataclass
class Officer:
    name: str
    role: str | None
    appointed_on: str | None
    resigned_on: str | None
    nationality: str | None
    country_of_residence: str | None
    occupation: str | None
    birth_year_month: str | None

    @property
    def active(self) -> bool:
        return self.resigned_on is None


def parse_officers(doc: dict) -> list[Officer]:
    out = []
    for it in doc.get("items", []):
        dob = it.get("date_of_birth") or {}
        ym = f"{dob['year']}-{int(dob['month']):02d}" if dob.get("year") and dob.get("month") else None
        out.append(Officer(it.get("name", ""), it.get("officer_role"), _iso(it.get("appointed_on")),
                           _iso(it.get("resigned_on")), it.get("nationality"), it.get("country_of_residence"),
                           it.get("occupation"), ym))
    return out


@dataclass
class CompanyRow:
    number: str
    name: str | None
    status: str | None
    category: str | None
    incorporated: str | None
    jurisdiction: str | None
    sic_codes: list[str]
    postcode: str | None
    line: int


def _bulk_date(s: str) -> str | None:
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    return _iso(f"{m.group(3)}-{m.group(2)}-{m.group(1)}") if m else _iso(s) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def iter_basic_company_csv(text: str, only: set[str] | None = None) -> Iterator[CompanyRow]:
    """Basic Company Data CSV. Header names are stripped: the real file has leading spaces in some."""
    rd = csv.DictReader(io.StringIO(text))
    for n, raw in enumerate(rd, 2):
        r = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        num = r.get("CompanyNumber", "").upper()
        if not num or (only is not None and num not in only):
            continue
        sics = [m.group(1) for k in sorted(r) if k.startswith("SICCode.SicText_")
                if (m := re.match(r"(\d{4,5})\b", r[k]))]
        status = r.get("CompanyStatus") or None
        yield CompanyRow(num, r.get("CompanyName") or None, status, r.get("CompanyCategory") or None,
                         _bulk_date(r.get("IncorporationDate", "")), r.get("CountryOfOrigin") or None, sics,
                         r.get("RegAddress.PostCode") or None, n)
