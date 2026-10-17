"""Debt facility amounts read from credit agreement text. Pure code, no LLM.

A tranche is taken only from a sentence that names a facility (term loan or revolver) and states a dollar
amount alongside "principal amount" or "Commitment". Margin grids and maturity tenors are not turned into
numbers here: they are returned as the cited sentence so a reader sees the terms, not a guess.
"""

from __future__ import annotations

import re
from decimal import Decimal

_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d“\"])")
_FACILITY = re.compile(r"\b(Term Loan [A-Z]|Term Loan|Revolving (?:Credit )?(?:Facility|Loans?)|Revolver)\b")
_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?)")
_CUE = re.compile(r"principal amount|Commitment", re.IGNORECASE)
_MATURITY = re.compile(r"Maturity Date[^.]{0,80}?(\w+ years? after the Closing Date|\d{4})", re.IGNORECASE)


def extract(pages: list[tuple[int, str]]) -> list[dict]:
    """pages: (number, text). One dict per facility sentence with a dollar amount, cited to its page."""
    out = []
    for num, text in pages:
        flat = re.sub(r"\s+", " ", text)
        for sent in _SENT.split(flat):
            s = sent.strip()
            fac = _FACILITY.search(s)
            amt = _AMOUNT.search(s)
            if not (fac and amt and _CUE.search(s)):
                continue
            out.append({
                "facility": fac.group(1),
                "amount": Decimal(amt.group(1).replace(",", "")),
                "page": num,
                "quote": s,
                "maturity_terms": [m.group(1) for m in _MATURITY.finditer(s)],
            })
    return out


# The pricing grid is printed as one row per level: "<level> <leverage test> <Term SOFR %> <Base Rate %>".
# Percentages are kept as printed (1.25 means 1.25%), so every stored value appears verbatim in its quote.
_GRID_ROW = re.compile(
    r"(?<![\d.])(\d)\s+([<>≤≥]=?\s?\d+\.\d+:1\.00)\s+(\d+(?:\.\d+)?)\s?%\s+(\d+(?:\.\d+)?)\s?%"
)
_MATURITY_CLAUSE = re.compile(r"Maturity Date\s*”?\s*means[^;]{0,160}")


def margin_grid(pages: list[tuple[int, str]]) -> list[dict]:
    """Term SOFR margin per pricing level, from a printed Applicable Margin table. Only rows that are
    complete (level, leverage test, SOFR %, base rate %) are returned."""
    out = []
    for num, text in pages:
        flat = re.sub(r"\s+", " ", text)
        for m in _GRID_ROW.finditer(flat):
            out.append({
                "level": int(m.group(1)),
                "leverage_test": m.group(2).replace(" ", ""),
                "sofr_pct": Decimal(m.group(3)),
                "base_pct": Decimal(m.group(4)),
                "page": num,
                "quote": m.group(0),
            })
    return out


def maturity_clauses(pages: list[tuple[int, str]]) -> list[dict]:
    """The sentence that defines the maturity date, cited. The tenor is returned as written (for example
    "three years after the Closing Date"), not converted to a calendar date, since the closing date is not
    stated in the clause."""
    out = []
    for num, text in pages:
        flat = re.sub(r"\s+", " ", text)
        for m in _MATURITY_CLAUSE.finditer(flat):
            out.append({"text": m.group(0).strip(), "page": num, "quote": m.group(0).strip()})
    return out
