"""Match a company name to a Companies House company number, with a confidence tier.

Input: the CH Basic Company Data CSV (free bulk download, index under data/api_samples).
Rules: exact (case-insensitive) name match links automatically. A normalised match (legal suffix,
punctuation and 'THE' removed) links only when exactly one active company has that name. Anything
else is a fuzzy candidate with a score and goes to review. Nothing fuzzy is ever auto-linked.
"""
from __future__ import annotations

import csv
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

_SUFFIX = re.compile(r"\b(LIMITED|LTD|PLC|LLP|L\s?P|CIC|INC|CORP|HOLDINGS?)\b\.?$")
_STRIP = re.compile(r"[^A-Z0-9 ]+")
FUZZY_MIN = 0.85


@dataclass(frozen=True)
class Match:
    query: str
    company_number: str | None  # for needs_review matches this is a suggestion, not a link
    company_name: str | None
    tier: str  # "exact" | "normalised" | "fuzzy" | "ambiguous" | "none"
    score: float
    needs_review: bool


def normalise(name: str) -> str:
    s = _STRIP.sub(" ", name.upper().replace("&", " AND "))
    s = re.sub(r"^THE\s+", "", s.strip())
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:  # drop stacked suffixes, e.g. 'X HOLDINGS LIMITED'
        prev, s = s, _SUFFIX.sub("", s).strip()
    return s


def load_candidates(ch_csv: Path, queries: list[str]) -> list[tuple[str, str, str, str]]:
    """One streaming pass. Keeps only rows whose first token appears in a query."""
    firsts = {normalise(q).split()[0] for q in queries if normalise(q)}
    out: list[tuple[str, str, str, str]] = []
    with open(ch_csv, encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader)]
        i_name, i_num = header.index("CompanyName"), header.index("CompanyNumber")
        i_status = header.index("CompanyStatus")
        for row in reader:
            if len(row) <= max(i_name, i_num, i_status):
                continue
            name = row[i_name].strip()
            toks = normalise(name).split()
            if toks and toks[0] in firsts:
                out.append((name, row[i_num].strip(), row[i_status].strip(), normalise(name)))
    return out


def match(query: str, candidates: list[tuple[str, str, str, str]]) -> Match:
    q_raw = query.strip()
    q_norm = normalise(q_raw)
    if not q_norm:
        return Match(query, None, None, "none", 0.0, True)
    active = [c for c in candidates if c[2].lower() == "active"]
    exact = [c for c in candidates if c[0].upper() == q_raw.upper()]
    if len(exact) == 1:
        return Match(query, exact[0][1], exact[0][0], "exact", 1.0, False)
    same = [c for c in candidates if c[3] == q_norm]
    if len(same) == 1:
        return Match(query, same[0][1], same[0][0], "normalised", 0.95, False)
    if len(same) > 1:
        live = [c for c in same if c[2].lower() == "active"]
        if len(live) == 1:
            return Match(query, live[0][1], live[0][0], "normalised", 0.95, False)
        return Match(query, None, None, "ambiguous", 0.0, True)
    best, best_score = None, 0.0
    for c in active or candidates:
        s = difflib.SequenceMatcher(None, q_norm, c[3]).ratio()
        if s > best_score:
            best, best_score = c, s
    if best is not None and best_score >= FUZZY_MIN:
        return Match(query, best[1], best[0], "fuzzy", round(best_score, 3), True)
    return Match(query, None, None, "none", round(best_score, 3), True)


CH_FILING_DOC = (
    "https://find-and-update.company-information.service.gov.uk"
    "/company/{number}/filing-history/{filing_id}/document?format=pdf"
)


@dataclass(frozen=True)
class SourcedRaise:
    query: str
    company_number: str
    filing_id: str
    source_url: str


def attach_sh01(m: Match, filing_id: str) -> SourcedRaise | None:
    """Attach an SH01 raise only to an auto-linked match. Review-tier matches never get a source."""
    if m.needs_review or m.company_number is None:
        return None
    return SourcedRaise(
        query=m.query,
        company_number=m.company_number,
        filing_id=filing_id,
        source_url=CH_FILING_DOC.format(number=m.company_number, filing_id=filing_id),
    )
